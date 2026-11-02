"""Structured facts (PLAN §5 KNOW, §11 rule 2): numbers/dates the agent may state come only from
**approved** rows here, never from chunk prose. Rows are created `pending` by ingestion (table
mapping or the Opus extractor) and approved/edited by an admin; approval bumps
`institutions.facts_version` (invalidates the cached tenant prompt block)."""

import datetime as dt
import uuid

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.db.base import Base, TenantMixin, TimestampsMixin, UUIDPkMixin, enum_check
from app.models.enums import FACT_ORIGINS, FACT_STATUSES, FEE_FREQUENCIES


class FactMixin(UUIDPkMixin, TenantMixin, TimestampsMixin):
    status: Mapped[str] = mapped_column(String(12), server_default="pending")
    ordinal: Mapped[int] = mapped_column(Integer, server_default="0")  # order in the source
    origin: Mapped[str] = mapped_column(String(8))
    academic_year: Mapped[str | None] = mapped_column(String(16))
    notes: Mapped[str | None] = mapped_column(Text)
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_quote: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    @declared_attr
    def source_document_id(cls) -> Mapped[uuid.UUID | None]:  # noqa: N805
        return mapped_column(
            UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
        )

    @declared_attr
    def approved_by(cls) -> Mapped[uuid.UUID | None]:  # noqa: N805
        return mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))

    @classmethod
    def fact_args(cls, table: str) -> tuple[object, ...]:
        return (
            enum_check("status", FACT_STATUSES),
            enum_check("origin", FACT_ORIGINS),
            Index(None, "institution_id", "status"),
        )


class Program(FactMixin, Base):
    __tablename__ = "programs"
    __table_args__ = FactMixin.fact_args("programs")

    name: Mapped[str] = mapped_column(String(200))
    level: Mapped[str | None] = mapped_column(String(80))
    duration: Mapped[str | None] = mapped_column(String(80))
    eligibility: Mapped[str | None] = mapped_column(Text)
    deadline: Mapped[dt.date | None] = mapped_column(Date)
    seats: Mapped[int | None] = mapped_column(Integer)


class FeeItem(FactMixin, Base):
    __tablename__ = "fee_items"
    __table_args__ = (
        *FactMixin.fact_args("fee_items"),
        enum_check("frequency", FEE_FREQUENCIES),
    )

    class_name: Mapped[str | None] = mapped_column(String(120))  # schools: class / "All classes"
    program_name: Mapped[str | None] = mapped_column(String(200))  # colleges/universities
    head: Mapped[str] = mapped_column(String(160))  # "Tuition fee", "Admission fee", ...
    amount_pkr: Mapped[int] = mapped_column(Integer)  # whole rupees, normalized in code
    frequency: Mapped[str] = mapped_column(String(16))


class KeyDate(FactMixin, Base):
    __tablename__ = "key_dates"
    __table_args__ = FactMixin.fact_args("key_dates")

    event: Mapped[str] = mapped_column(String(200))
    date: Mapped[dt.date] = mapped_column(Date)
    end_date: Mapped[dt.date | None] = mapped_column(Date)


class Scholarship(FactMixin, Base):
    __tablename__ = "scholarships"
    __table_args__ = FactMixin.fact_args("scholarships")

    name: Mapped[str] = mapped_column(String(200))
    rule: Mapped[str | None] = mapped_column(Text)  # eligibility criteria
    amount: Mapped[str | None] = mapped_column(String(120))  # "50% of tuition"


class TransportRoute(FactMixin, Base):
    __tablename__ = "transport_routes"
    __table_args__ = FactMixin.fact_args("transport_routes")

    name: Mapped[str] = mapped_column(String(120))
    areas: Mapped[str | None] = mapped_column(Text)
    monthly_pkr: Mapped[int] = mapped_column(Integer)


FACT_MODELS: dict[str, type[FactMixin]] = {
    "programs": Program,
    "fee_items": FeeItem,
    "key_dates": KeyDate,
    "scholarships": Scholarship,
    "transport_routes": TransportRoute,
}
