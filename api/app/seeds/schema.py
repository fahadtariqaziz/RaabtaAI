"""Pydantic schema for `seeds/<name>/seed.yaml` — validates demo data before it touches the DB."""

from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import (
    INSTITUTION_TYPES,
    LANGUAGES,
    LEAD_SOURCES,
    LEAD_STATUSES,
    MEMBERSHIP_ROLES,
    SLOT_KINDS,
)

SEEDS_DIR = Path(__file__).resolve().parents[2] / "seeds"
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InstitutionSeed(_Strict):
    slug: str = Field(pattern=r"^[a-z0-9-]{3,64}$")
    name: str
    type: Literal[INSTITUTION_TYPES]  # type: ignore[valid-type]
    city: str
    timezone: str = "Asia/Karachi"
    languages: list[Literal[LANGUAGES]]  # type: ignore[valid-type]
    quiet_hours: dict[str, str]
    settings: dict[str, Any] = {}


class UserSeed(_Strict):
    role: Literal[MEMBERSHIP_ROLES]  # type: ignore[valid-type]
    email: EmailStr
    name: str


class SlotRule(_Strict):
    kind: Literal[SLOT_KINDS]  # type: ignore[valid-type]
    weekdays: list[Weekday]
    times: list[str] = Field(min_length=1)  # local "HH:MM"
    duration_minutes: int = Field(gt=0, le=480)
    capacity: int = Field(gt=0)
    weeks: int = Field(gt=0, le=12)
    location: str


class LeadSeed(_Strict):
    student_name: str
    interest: str
    status: Literal[LEAD_STATUSES]  # type: ignore[valid-type]
    source: Literal[LEAD_SOURCES]  # type: ignore[valid-type]


class ContactSeed(_Strict):
    name: str
    wa_id: str = Field(pattern=r"^92\d{10}$")
    lang: Literal[LANGUAGES]  # type: ignore[valid-type]
    lead: LeadSeed


class FeeItem(_Strict):
    class_name: str | None = None
    program: str | None = None
    head: str
    amount_pkr: int = Field(gt=0)
    frequency: Literal["one_time", "monthly", "annual", "per_semester"]
    notes: str | None = None


class TransportRoute(_Strict):
    name: str
    areas: str
    monthly_pkr: int = Field(gt=0)


class KeyDate(_Strict):
    event: str
    date: date
    notes: str | None = None


class Scholarship(_Strict):
    name: str
    rule: str
    amount: str


class Program(_Strict):
    name: str
    level: str
    duration: str
    eligibility: str
    seats: int | None = None


class Facts(_Strict):
    academic_year: str
    classes: list[str] = []
    programs: list[Program] = []
    fee_items: list[FeeItem]
    transport_routes: list[TransportRoute] = []
    key_dates: list[KeyDate] = []
    scholarships: list[Scholarship] = []


class ProspectusSection(_Strict):
    heading: str
    body: str
    lang: Literal["en", "ur"] = "en"


class Prospectus(_Strict):
    title: str
    sections: list[ProspectusSection]


class SeedFile(_Strict):
    institution: InstitutionSeed
    users: list[UserSeed]
    slots: SlotRule
    contacts: list[ContactSeed]
    facts: Facts
    prospectus: Prospectus


def seed_dirs() -> list[Path]:
    return sorted(p for p in SEEDS_DIR.iterdir() if (p / "seed.yaml").is_file())


def load_seed(directory: Path) -> SeedFile:
    with (directory / "seed.yaml").open(encoding="utf-8") as fh:
        return SeedFile.model_validate(yaml.safe_load(fh))
