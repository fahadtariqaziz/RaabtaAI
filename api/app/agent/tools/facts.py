"""Typed fact tools (PLAN §9.3, §11 rule 2, G3): only **approved** rows are served; every row
carries a deterministic `source_id` the reply is checked against. Filtering is deterministic
(whole-word match on normalized text); when a filter matches nothing the full (capped) table is
returned with a note so the model can say what exists."""

import datetime as dt
import json
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.registry import Source, ToolContext, ToolRuntime, source_id
from app.kb.text import normalize
from app.models.facts import FeeItem, KeyDate, Program, Scholarship, TransportRoute
from app.services.kb_facts import fields_of, outs

MAX_ROWS = 40
FREQUENCY_LABEL = {
    "one_time": "one-time",
    "monthly": "monthly",
    "quarterly": "quarterly",
    "annual": "annual",
    "per_semester": "per semester",
}


class FactRow(BaseModel):
    source_id: str
    academic_year: str | None
    notes: str | None
    fields: dict[str, Any]


class FactsOutput(BaseModel):
    kind: str
    rows: list[FactRow]
    note: str | None = None

    def render(self) -> str:
        payload: dict[str, Any] = {"kind": self.kind, "rows": [r.model_dump() for r in self.rows]}
        if self.note:
            payload["note"] = self.note
        if not self.rows:
            payload["note"] = "No approved data for this. Use the fallback phrase; do not guess."
        return json.dumps(payload, ensure_ascii=False, default=str)


def _tokens(text: str | None) -> set[str]:
    return set(normalize(text or "").split())


def _matches(query: str | None, *values: str | None) -> bool:
    """Whole-word containment either way ("class 3" ≠ "class 13"; "computer science" ⊂ "bs
    computer science")."""
    q = _tokens(query)
    if not q:
        return True
    for value in values:
        v = _tokens(value)
        if v and (q <= v or v <= q):
            return True
    return False


async def _serve(
    session: AsyncSession,
    ctx: ToolContext,
    kind: str,
    rows: list[Any],
    keep: list[Any],
    note_if_none: str,
) -> FactsOutput:
    note = None
    if not keep and rows:
        keep, note = rows, note_if_none
    keep = keep[:MAX_ROWS]
    cited = {o.id: o for o in await outs(session, kind, keep)}
    out_rows: list[FactRow] = []
    sources: list[Source] = []
    for row in keep:
        fields = {
            k: (v.isoformat() if isinstance(v, dt.date) else v)
            for k, v in fields_of(kind, row).items()
            if v is not None
        }
        if kind == "fee_items":
            fields["frequency"] = FREQUENCY_LABEL.get(fields.get("frequency", ""), "")
        sid = source_id("F", kind, json.dumps(fields, sort_keys=True), row.academic_year)
        out_rows.append(
            FactRow(source_id=sid, academic_year=row.academic_year, notes=row.notes, fields=fields)
        )
        text = "; ".join(f"{k}: {v}" for k, v in fields.items())
        if row.notes:
            text += f"; notes: {row.notes}"
        citation = cited[row.id].source
        sources.append(
            Source(
                id=sid,
                kind="fact",
                text=f"{kind}: {text}",
                citation=citation.model_dump(mode="json") if citation else None,
            )
        )
    ctx.add_sources(sources)
    return FactsOutput(kind=kind, rows=out_rows, note=note)


async def _approved(session: AsyncSession, model: Any) -> list[Any]:
    stmt = select(model).where(model.status == "approved").order_by(model.ordinal, model.id)
    return list((await session.scalars(stmt)).all())


class FeeTableInput(BaseModel):
    program_or_class: str | None = Field(
        description='Class or program as the institution names it, e.g. "Class 3", "Playgroup", '
        '"BS Computer Science"; null for the whole table'
    )
    academic_year: str | None = Field(description='e.g. "2026-27"; null for current data')


async def get_fee_table(
    args: FeeTableInput, ctx: ToolContext, session: AsyncSession, runtime: ToolRuntime
) -> FactsOutput:
    rows = await _approved(session, FeeItem)
    if args.academic_year:
        rows = [r for r in rows if not r.academic_year or r.academic_year == args.academic_year]
    general = [r for r in rows if _tokens(r.class_name) & {"all"}]
    keep = (
        [r for r in rows if _matches(args.program_or_class, r.class_name, r.program_name)]
        if args.program_or_class
        else rows
    )
    if keep and args.program_or_class:  # school-wide heads ("All classes") apply to every class
        keep = [*keep, *[r for r in general if r not in keep]]
        keep.sort(key=lambda r: (r.ordinal, str(r.id)))
    return await _serve(
        session, ctx, "fee_items", rows, keep, "No exact match for that class/program; full table."
    )


class ProgramsInput(BaseModel):
    level: str | None = Field(
        description='Optional filter, e.g. "BS", "MS", "Intermediate", "FSc", or a program name'
    )


async def get_programs(
    args: ProgramsInput, ctx: ToolContext, session: AsyncSession, runtime: ToolRuntime
) -> FactsOutput:
    rows = await _approved(session, Program)
    keep = [r for r in rows if _matches(args.level, r.level, r.name) or _sub(args.level, r.name)]
    return await _serve(session, ctx, "programs", rows, keep, "No match for that level; all.")


def _sub(query: str | None, *values: str | None) -> bool:
    q = normalize(query or "")
    return bool(q) and any(q in normalize(v or "") for v in values)


class KeyDatesInput(BaseModel):
    kind: str | None = Field(
        description='Optional filter word, e.g. "test", "last date", "merit", "session"; null = all'
    )


async def get_key_dates(
    args: KeyDatesInput, ctx: ToolContext, session: AsyncSession, runtime: ToolRuntime
) -> FactsOutput:
    rows = await _approved(session, KeyDate)
    words = _tokens(args.kind)
    keep = [r for r in rows if not words or words & _tokens(f"{r.event} {r.notes or ''}")]
    return await _serve(session, ctx, "key_dates", rows, keep, "No date matched; all dates.")


class NoInput(BaseModel):
    pass


async def get_scholarships(
    args: NoInput, ctx: ToolContext, session: AsyncSession, runtime: ToolRuntime
) -> FactsOutput:
    rows = await _approved(session, Scholarship)
    return await _serve(session, ctx, "scholarships", rows, rows, "")


class TransportInput(BaseModel):
    area: str | None = Field(description="Area/locality the contact lives in; null for all routes")


async def get_transport_routes(
    args: TransportInput, ctx: ToolContext, session: AsyncSession, runtime: ToolRuntime
) -> FactsOutput:
    rows = await _approved(session, TransportRoute)
    keep = [r for r in rows if _sub(args.area, r.areas, r.name)] if args.area else rows
    return await _serve(
        session, ctx, "transport_routes", rows, keep, "That area is not listed; all routes."
    )
