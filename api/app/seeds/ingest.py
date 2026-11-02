"""Run the demo institutions' documents through the real ingestion pipeline (step 2.8.3,
`make ingest-seeds`). Idempotent: an identical file that is already `ready` is skipped; an
unfinished one is resumed.

Facts for the demo: spreadsheets map to fee_items/transport_routes deterministically. Prospectus
facts (programs, key dates, scholarships) come from the Opus extractor when `KB_FACTS_LLM=1`;
otherwise they are loaded from `seed.yaml` (origin `seed`, attributed to the prospectus) so the
demo works without API spend. `approve=True` approves all pending facts (demo only)."""

import hashlib
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import admin_session, tenant_session
from app.kb.ingest import IngestDeps, ingest_document
from app.models.core import Institution
from app.models.facts import FACT_MODELS
from app.models.kb import Document
from app.seeds.documents import FEE_XLSX, PROSPECTUS_DOCX, ensure_documents
from app.seeds.schema import SeedFile
from app.services.kb_documents import create_document
from app.services.kb_facts import approve_all, replace_document_facts


@dataclass
class SeedIngestResult:
    slug: str
    documents: dict[str, str] = field(default_factory=dict)  # filename -> final status
    seed_facts: dict[str, int] = field(default_factory=dict)
    approved: int = 0


def seed_prospectus_facts(seed: SeedFile) -> dict[str, list[dict[str, Any]]]:
    facts = seed.facts
    year = facts.academic_year
    return {
        "programs": [
            {
                "name": p.name,
                "level": p.level,
                "duration": p.duration,
                "eligibility": p.eligibility,
                "seats": p.seats,
                "academic_year": year,
            }
            for p in facts.programs
        ],
        "key_dates": [
            {"event": d.event, "date": d.date, "notes": d.notes, "academic_year": year}
            for d in facts.key_dates
        ],
        "scholarships": [
            {"name": s.name, "rule": s.rule, "amount": s.amount, "academic_year": year}
            for s in facts.scholarships
        ],
    }


async def _has_seed_facts(session: AsyncSession, document_id: uuid.UUID) -> bool:
    for model in FACT_MODELS.values():
        found = await session.scalar(
            select(model.id)
            .where(model.source_document_id == document_id, model.origin == "seed")
            .limit(1)
        )
        if found is not None:
            return True
    return False


async def ingest_seed_institution(
    deps: IngestDeps, seed: SeedFile, directory: Path, *, approve: bool = True
) -> SeedIngestResult:
    result = SeedIngestResult(slug=seed.institution.slug)
    async with admin_session(deps.sessionmaker) as session:
        inst_id = await session.scalar(
            select(Institution.id).where(Institution.slug == seed.institution.slug)
        )
    if inst_id is None:
        raise RuntimeError(f"institution {seed.institution.slug} not seeded — run `make seed`")
    titles = {
        FEE_XLSX: f"{seed.institution.name} — Fee structure",
        PROSPECTUS_DOCX: seed.prospectus.title,
    }
    doc_ids: dict[str, uuid.UUID] = {}
    for path in ensure_documents(seed, directory):
        data = path.read_bytes()
        checksum = hashlib.sha256(data).hexdigest()
        async with tenant_session(deps.sessionmaker, inst_id) as session:
            existing = await session.scalar(
                select(Document).where(
                    Document.checksum == checksum, Document.status != "superseded"
                )
            )
            if existing is None:
                existing = await create_document(
                    session,
                    deps.blobstore,
                    institution_id=inst_id,
                    user_id=None,
                    data=data,
                    filename=path.name,
                    title=titles[path.name],
                )
            doc_ids[path.name] = existing.id
        result.documents[path.name] = await ingest_document(deps, inst_id, doc_ids[path.name])
    async with tenant_session(deps.sessionmaker, inst_id) as session:
        prospectus = doc_ids.get(PROSPECTUS_DOCX)
        if (
            not deps.settings.kb_facts_llm
            and prospectus
            and not await _has_seed_facts(session, prospectus)
        ):
            result.seed_facts = await replace_document_facts(
                session, inst_id, prospectus, seed_prospectus_facts(seed), "seed"
            )
        if approve:
            result.approved = await approve_all(session, inst_id)
    return result
