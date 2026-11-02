# ADR 0002 — Embeddings provider (D-01)

- Date: 2026-11-02 · Status: **accepted** (user, 2026-11-02) — Voyage `voyage-3.5`

## Context
Anthropic has no embeddings API. Retrieval must work for English, Urdu (Nastaleeq script) and
Roman Urdu. No embedding model is trained on Roman Urdu, so RaabtaAI search is hybrid (PLAN §5
KNOW): dense vectors + Postgres FTS + `pg_trgm` + a Roman-Urdu/Urdu synonym table
(`api/seeds/ru_synonyms.csv`), fused with RRF. The dense leg's job is mainly English↔Urdu-script
semantic matching.

Candidates (both 1024-d, so `chunks.embedding vector(1024)` fits either):
- **Voyage `voyage-3.5`** (hosted; Anthropic's documented embedding partner; `input_type`
  query/document; cents per corpus).
- **`BAAI/bge-m3`** (self-hosted via Text-Embeddings-Inference; no per-call cost, needs a box
  with ~2–4 GB RAM — hard on a free host).

## Method
`uv run python -m scripts.bakeoff_embeddings --providers fake,voyage[,bge_m3]` re-embeds the
ingested demo institutions and runs `api/evals/datasets/retrieval.yaml` (60 Q: 20 EN / 20 UR /
20 Roman Urdu) dense-only and hybrid; report → `api/evals/reports/bakeoff-*.md`.

Baseline without any real model (offline hashing embedder `fake-hash-v1`, 2026-11-02):

| run | recall@1 | recall@5 | MRR | UR recall@1 |
|---|---|---|---|---|
| hybrid (fake dense + FTS + trigram + synonyms) | 0.85 | 1.00 | 0.92 | 0.75 |
| lexical only (FTS + trigram + synonyms) | 0.77 | 1.00 | 0.87 | 0.70 |

Live bake-off, 2026-11-02 (60 Q, same corpus, `evals/reports/bakeoff-20261102-171723.md`):

| run | recall@1 | recall@3 | MRR | EN r@1 | Roman Urdu r@1 | Urdu r@1 |
|---|---|---|---|---|---|---|
| fake · dense only | 0.80 | 1.00 | 0.89 | 0.90 | 0.85 | 0.65 |
| fake · hybrid | 0.83 | 0.97 | 0.91 | 0.95 | 0.85 | 0.70 |
| voyage-3.5 · dense only | 0.82 | 1.00 | 0.91 | 0.80 | 0.85 | 0.80 |
| **voyage-3.5 · hybrid** | **0.88** | **1.00** | **0.94** | 0.95 | 0.85 | **0.85** |

Voyage's gain is where expected: Urdu script (+15 pts recall@1 hybrid). bge-m3 was not run (no
host for it; revisit only if Voyage cost/latency becomes a problem).

Caveat: the demo corpus is ~4 chunks per institution, so recall@5 saturates; compare recall@1,
MRR and the Urdu subset. Repeat on a real client prospectus before pilots.

## Decision
**Voyage `voyage-3.5`** (`EMBEDDING_PROVIDER=voyage`); `bge-m3` stays available behind the same
`EmbeddingProvider` interface. The Voyage account currently has **no payment method → 3 requests/min,
10K tokens/min**: fine for dev/bake-offs (the provider waits out 429s, evals batch queries), not for
live traffic — add billing before pilots (free 200M-token allowance still applies).

## Consequences
- Switching provider = `reembed_all` per institution (no schema change while dim stays 1024).
- Prod refuses `EMBEDDING_PROVIDER=fake`.
- Query embeddings are a per-message cost (tiny) and a network dependency of the agent's
  `search_knowledge` tool; the lexical legs still answer if the dense leg errors (step 3.x).
