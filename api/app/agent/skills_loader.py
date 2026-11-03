"""Skill packs (PLAN §9.2): `app/skills/<name>/SKILL.md` + `skill.yaml`.

`select()` picks the skills whose `load_when` matches the turn (institution type, module, router
intents, channel, language, node) plus router-suggested skills that fit the institution/module;
order is deterministic (priority desc, name) and the total is capped (agent skills block ≤ 1.5k
tokens, PLAN §7) so the cached system[2] block repeats across conversations."""

import functools
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.kb.text import estimate_tokens

SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"
SKILLS_BUDGET = 1500
SKILL_MAX = 1200


class LoadWhen(BaseModel):
    model_config = ConfigDict(extra="forbid")

    institution_type: list[str] = Field(default_factory=list)
    module: list[str] = Field(default_factory=list)
    intents: list[str] = Field(default_factory=list)
    channel: list[str] = Field(default_factory=list)
    language: list[str] = Field(default_factory=list)
    node: list[str] = Field(default_factory=lambda: ["agent"])


class SkillMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    description: str
    load_when: LoadWhen
    priority: int = 50
    max_tokens: int = SKILL_MAX
    always: bool = False


@dataclass(frozen=True)
class Skill:
    meta: SkillMeta
    body: str
    tokens: int

    @property
    def name(self) -> str:
        return self.meta.name

    @property
    def tag(self) -> str:
        return f"{self.meta.name}@{self.meta.version}"


@dataclass(frozen=True)
class TurnFacts:
    institution_type: str
    module: str
    intents: tuple[str, ...] = ()
    channel: str = "widget"
    language: str = "en"
    node: str = "agent"
    requested: tuple[str, ...] = field(default=())  # router suggestions


@functools.cache
def load_skills() -> dict[str, Skill]:
    skills: dict[str, Skill] = {}
    for meta_path in sorted(SKILLS_DIR.glob("*/skill.yaml")):
        meta = SkillMeta.model_validate(yaml.safe_load(meta_path.read_text(encoding="utf-8")))
        if meta.name != meta_path.parent.name:
            raise ValueError(f"skill {meta_path.parent.name}: name mismatch {meta.name!r}")
        body = (meta_path.parent / "SKILL.md").read_text(encoding="utf-8").strip()
        tokens = estimate_tokens(body)
        if tokens > min(meta.max_tokens, SKILL_MAX):
            raise ValueError(f"skill {meta.name}: {tokens} tokens > cap {meta.max_tokens}")
        skills[meta.name] = Skill(meta=meta, body=body, tokens=tokens)
    return skills


def _matches(when: LoadWhen, facts: TurnFacts, *, context_only: bool = False) -> bool:
    checks = [
        (when.institution_type, facts.institution_type),
        (when.module, facts.module),
        (when.node, facts.node),
    ]
    if not context_only:
        checks += [(when.channel, facts.channel), (when.language, facts.language)]
    if any(allowed and value not in allowed for allowed, value in checks):
        return False
    return context_only or not when.intents or bool(set(when.intents) & set(facts.intents))


def select(facts: TurnFacts, *, budget: int = SKILLS_BUDGET) -> list[Skill]:
    skills = load_skills()
    chosen = {
        s.name
        for s in skills.values()
        if (s.meta.always and _matches(s.meta.load_when, facts, context_only=True))
        or _matches(s.meta.load_when, facts)
    }
    for name in facts.requested:  # router hints: only if they fit institution/module/node
        skill = skills.get(name)
        if skill and _matches(skill.meta.load_when, facts, context_only=True):
            chosen.add(name)
    ordered = sorted((skills[n] for n in chosen), key=lambda s: (-s.meta.priority, s.name))
    kept: list[Skill] = []
    used = 0
    for skill in ordered:
        if used + skill.tokens <= budget:
            kept.append(skill)
            used += skill.tokens
    return kept


def render(skills: list[Skill]) -> str:
    """System block 3 (cached). Empty string when no skill applies."""
    return "\n\n".join(f"# Skill: {s.name}\n{s.body}" for s in skills)


def available_for_router(institution_type: str) -> list[str]:
    """Skill names the router may suggest for this institution (agent node only)."""
    return [
        s.name
        for s in load_skills().values()
        if "agent" in s.meta.load_when.node
        and institution_type in (s.meta.load_when.institution_type or [institution_type])
    ]
