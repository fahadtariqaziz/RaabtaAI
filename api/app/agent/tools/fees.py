"""Fee-module tools (PLAN §9.3) — registered now with their permission gates (G4) so the fee
persona, router and evals see the final tool surface; implementations land in Phase 7."""

import datetime as dt

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.registry import ToolContext, ToolError, ToolRuntime

NOT_ENABLED = (
    "The fee module is not enabled for this institution yet. Apologise briefly and call "
    "handoff_to_human with reason fee_module_unavailable so the accounts office replies."
)


class VerifyInput(BaseModel):
    student_name: str = Field(min_length=1, max_length=120)
    class_or_roll: str = Field(min_length=1, max_length=40)
    phone_last4: str | None = Field(max_length=4, description="Last 4 digits of registered phone")


class StudentRefInput(BaseModel):
    student_ref: str = Field(description="Reference returned by verify_parent")


class PromiseInput(BaseModel):
    student_ref: str
    promised_date: dt.date
    amount_pkr: int | None = Field(ge=0, description="Only if the contact stated an amount")
    note: str | None = Field(max_length=300)


class ProofInput(BaseModel):
    student_ref: str
    media_id: str = Field(description="Id of the image the contact sent")


class DisputeInput(BaseModel):
    student_ref: str
    summary: str = Field(max_length=500)


class PendingOutput(BaseModel):
    status: str


async def not_enabled(
    args: BaseModel, ctx: ToolContext, session: AsyncSession, runtime: ToolRuntime
) -> PendingOutput:
    raise ToolError(NOT_ENABLED)
