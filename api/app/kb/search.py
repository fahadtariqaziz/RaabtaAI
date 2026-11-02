"""Hybrid retrieval (step 2.5, PLAN §5 KNOW):

1. dense — cosine distance on `chunks.embedding` (HNSW),
2. keyword — Postgres FTS (`simple` config over the normalized text) with OR-ed terms,
3. fuzzy — `pg_trgm` word similarity of each query word against `text_norm` (Roman-Urdu spelling
   variance: "dakhla"/"dakhila", "fees"/"fis"),

plus query expansion from `seeds/ru_synonyms.csv` (Roman Urdu / Urdu → English terms). The agent
sends 1–3 queries per call; every (query × leg) ranking is fused with Reciprocal Rank Fusion.
Only chunks of `ready` documents that are not flagged `suspicious` are searchable. Tenant scoping:
RLS (session GUC) **and** an explicit `institution_id` predicate."""

import csv
import functools
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.kb.citations import Citation, make_quote
from app.kb.embeddings import EmbeddingError, EmbeddingProvider
from app.kb.text import normalize, words
from app.models.kb import Chunk, Document

log = structlog.get_logger(__name__)
SYNONYMS_CSV = Path(__file__).resolve().parents[2] / "seeds" / "ru_synonyms.csv"
RRF_K = 60
PER_LEG = 20
MAX_QUERIES = 3
TRGM_THRESHOLD = 0.5
LEGS = ("vector", "fts", "trgm")

# Words that carry no retrieval signal in EN / Roman Urdu questions.
_STOPWORDS_TEXT = (
    "a an the is are was were be been of to in on at for from by with and or what which who "
    "whom how when where why do does did can could would should will shall may might i you we "
    "they he she it my your our their me us them this that these those there here please tell "
    "me about any some hai kya ka ki ke ko mein se aur bhi ap aap apka apki apke hum mujhe "
    "mera meri ye yeh wo woh kitna kab kahan kaise kaun batain bataen bata dein chahiye hota "
    "hoti hain tha thi raha rahi nahi na ji sir madam plz pls"
)
STOPWORDS = frozenset(_STOPWORDS_TEXT.split())


@functools.cache
def synonyms() -> dict[str, tuple[str, ...]]:
    table: dict[str, tuple[str, ...]] = {}
    with SYNONYMS_CSV.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            key = normalize(row["term"].strip())
            extra = tuple(words(row["expansion"]))
            if key and extra:
                table[key] = tuple(dict.fromkeys(table.get(key, ()) + extra))
    return table


def expand(query: str) -> list[str]:
    """Normalized content words of `query` + synonym expansions (unigrams and bigrams)."""
    tokens = words(query)
    syn = synonyms()
    out: list[str] = [t for t in tokens if t not in STOPWORDS]
    for i, tok in enumerate(tokens):
        out.extend(syn.get(tok, ()))
        if i + 1 < len(tokens):
            out.extend(syn.get(f"{tok} {tokens[i + 1]}", ()))
    return [t for t in dict.fromkeys(out) if t not in STOPWORDS]


@dataclass
class SearchHit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    title: str
    page: int | None
    heading: str | None
    text: str
    tokens: int
    score: float = 0.0
    legs: dict[str, int] = field(default_factory=dict)  # "fts#1" -> rank

    def citation(self, terms: list[str] | None = None) -> Citation:
        return Citation(
            document_id=self.document_id,
            title=self.title,
            page=self.page,
            chunk_id=self.chunk_id,
            quote=make_quote(self.text, terms),
        )


def _base(institution_id: uuid.UUID):  # type: ignore[no-untyped-def]
    return (
        select(
            Chunk.id,
            Chunk.document_id,
            Document.title,
            Chunk.page,
            Chunk.heading,
            Chunk.text,
            Chunk.tokens,
        )
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Chunk.institution_id == institution_id,
            Document.institution_id == institution_id,
            Document.status == "ready",
            Chunk.suspicious.is_(False),
        )
    )


async def _vector_leg(
    session: AsyncSession, institution_id: uuid.UUID, vec: list[float], limit: int
) -> list[tuple[object, ...]]:
    stmt = (
        _base(institution_id)
        .where(Chunk.embedding.is_not(None))
        .order_by(Chunk.embedding.cosine_distance(vec))
        .limit(limit)
    )
    return [tuple(r) for r in (await session.execute(stmt)).all()]


def _tsquery(terms: list[str]) -> str | None:
    clean = ["".join(ch for ch in t if ch.isalnum()) for t in terms]
    clean = [c for c in dict.fromkeys(clean) if c]
    return " | ".join(clean) if clean else None


async def _fts_leg(
    session: AsyncSession, institution_id: uuid.UUID, terms: list[str], limit: int
) -> list[tuple[object, ...]]:
    query = _tsquery(terms)
    if query is None:
        return []
    tsq = func.to_tsquery(text("'simple'::regconfig"), query)
    stmt = (
        _base(institution_id)
        .where(Chunk.tsv.op("@@")(tsq))
        .order_by(func.ts_rank_cd(Chunk.tsv, tsq).desc(), Chunk.ordinal)
        .limit(limit)
    )
    return [tuple(r) for r in (await session.execute(stmt)).all()]


_TRGM_SQL = text(
    """
    SELECT c.id, sum(word_similarity(t, c.text_norm)) AS score
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    CROSS JOIN unnest(CAST(:terms AS text[])) AS t
    WHERE c.institution_id = :inst AND d.institution_id = :inst
      AND d.status = 'ready' AND NOT c.suspicious
      AND t <% c.text_norm
    GROUP BY c.id
    ORDER BY score DESC
    LIMIT :limit
    """
)


async def _trgm_leg(
    session: AsyncSession, institution_id: uuid.UUID, terms: list[str], limit: int
) -> list[uuid.UUID]:
    usable = [t for t in terms if len(t) >= 3][:12]
    if not usable:
        return []
    await session.execute(
        text("SELECT set_config('pg_trgm.word_similarity_threshold', :v, true)"),
        {"v": str(TRGM_THRESHOLD)},
    )
    rows = await session.execute(
        _TRGM_SQL, {"terms": usable, "inst": institution_id, "limit": limit}
    )
    return [r[0] for r in rows.all()]


async def search(
    session: AsyncSession,
    institution_id: uuid.UUID,
    queries: list[str],
    provider: EmbeddingProvider | None,
    *,
    top_k: int = 5,
    legs: tuple[str, ...] = LEGS,
) -> list[SearchHit]:
    """Fused top-k chunks for 1–3 queries. `provider=None` skips the dense leg."""
    queries = [q.strip() for q in dict.fromkeys(queries) if q and q.strip()][:MAX_QUERIES]
    if not queries:
        return []
    expanded = [expand(q) for q in queries]
    hits: dict[uuid.UUID, SearchHit] = {}
    rankings: list[tuple[str, list[uuid.UUID]]] = []

    def remember(rows: list[tuple[object, ...]]) -> list[uuid.UUID]:
        ids = []
        for row in rows:
            cid = row[0]
            assert isinstance(cid, uuid.UUID)  # noqa: S101
            if cid not in hits:
                hits[cid] = SearchHit(
                    chunk_id=cid,
                    document_id=row[1],  # type: ignore[arg-type]
                    title=row[2],  # type: ignore[arg-type]
                    page=row[3],  # type: ignore[arg-type]
                    heading=row[4],  # type: ignore[arg-type]
                    text=row[5],  # type: ignore[arg-type]
                    tokens=row[6],  # type: ignore[arg-type]
                )
            ids.append(cid)
        return ids

    if "vector" in legs and provider is not None:
        texts = [" ".join([q, *terms]) for q, terms in zip(queries, expanded, strict=True)]
        try:
            vectors = await provider.embed(texts, "query")
        except EmbeddingError as exc:  # lexical legs still answer
            log.warning("kb.search.dense_leg_failed", error=str(exc))
            vectors = []
        for i, vec in enumerate(vectors):
            rows = await _vector_leg(session, institution_id, vec, PER_LEG)
            rankings.append((f"vector#{i + 1}", remember(rows)))
    for i, terms in enumerate(expanded):
        if "fts" in legs:
            rows = await _fts_leg(session, institution_id, terms, PER_LEG)
            rankings.append((f"fts#{i + 1}", remember(rows)))
        if "trgm" in legs:
            ids = await _trgm_leg(session, institution_id, terms, PER_LEG)
            missing = [cid for cid in ids if cid not in hits]
            if missing:
                extra = await session.execute(_base(institution_id).where(Chunk.id.in_(missing)))
                remember([tuple(r) for r in extra.all()])
            rankings.append((f"trgm#{i + 1}", [cid for cid in ids if cid in hits]))

    for leg, ids in rankings:
        for rank, cid in enumerate(ids, start=1):
            hits[cid].score += 1.0 / (RRF_K + rank)
            hits[cid].legs[leg] = rank
    ranked = sorted(hits.values(), key=lambda h: (-h.score, str(h.chunk_id)))
    return [h for h in ranked if h.legs][:top_k]


def pack(hits: list[SearchHit], budget: int = 2000) -> tuple[list[SearchHit], int]:
    """Keep hits in rank order while the token total fits `budget` (PLAN §7: chunks ≤ 2k).
    The first hit is always kept (truncated to the budget if it alone is larger)."""
    kept: list[SearchHit] = []
    used = 0
    for hit in hits:
        if used + hit.tokens <= budget:
            kept.append(hit)
            used += hit.tokens
        elif not kept:
            ratio = budget / max(hit.tokens, 1)
            cut = hit.text[: max(1, int(len(hit.text) * ratio))]
            kept.append(
                SearchHit(**{**hit.__dict__, "text": cut, "tokens": budget, "legs": hit.legs})
            )
            used = budget
    return kept, used
