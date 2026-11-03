"""`search_knowledge` — hybrid KB search (PLAN §5 KNOW). Passages describe; numbers come from
the fact tools (D-08). Results are framed as `<source>` data blocks (G1)."""

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.registry import Source, ToolContext, ToolRuntime, source_id
from app.kb.search import pack, search


class SearchInput(BaseModel):
    queries: list[str] = Field(
        min_length=1,
        max_length=3,
        description="1-3 short queries: the contact's wording, an English rewrite, and an "
        "Urdu-script rewrite if they wrote in Urdu",
    )
    top_k: int | None = Field(default=None, ge=1, le=5, description="Max passages (default 5)")


class Passage(BaseModel):
    source_id: str
    title: str
    page: int | None
    text: str


class SearchOutput(BaseModel):
    results: list[Passage]

    def render(self) -> str:
        if not self.results:
            return "No matching passages in the institution's documents."
        return "\n".join(
            f'<source id="{p.source_id}" title="{p.title}" page="{p.page or "-"}">\n'
            f"{p.text}\n</source>"
            for p in self.results
        )


async def search_knowledge(
    args: SearchInput, ctx: ToolContext, session: AsyncSession, runtime: ToolRuntime
) -> SearchOutput:
    hits = await search(
        session, ctx.institution_id, args.queries, runtime.embedder, top_k=args.top_k or 5
    )
    kept, _ = pack(hits, 2000)
    passages: list[Passage] = []
    sources: list[Source] = []
    for hit in kept:
        sid = source_id("S", hit.title, hit.page, hit.text)
        passages.append(Passage(source_id=sid, title=hit.title, page=hit.page, text=hit.text))
        citation: dict[str, Any] = hit.citation(args.queries).model_dump(mode="json")
        sources.append(Source(id=sid, kind="chunk", text=hit.text, citation=citation))
    ctx.add_sources(sources)
    return SearchOutput(results=passages)
