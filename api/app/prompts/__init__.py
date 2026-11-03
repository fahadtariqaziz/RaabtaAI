"""Versioned prompt files (PLAN §9.1): `app/prompts/<name>.md` with YAML front-matter

    name, version (semver), model_key, effort?, max_tokens?, cacheable, changelog

Changing a prompt is a release (PLAN §12). The content hash (body only) is logged in `llm_runs`.
Prompts never contain dates or tenant data — the tenant block is rendered from
`tenant_block.md.j2` deterministically (sorted keys, no timestamps)."""

import functools
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jinja2
import yaml

from app.core.models_registry import NODES, spec_for

PROMPTS_DIR = Path(__file__).resolve().parent
MODEL_KEYS = {*NODES, "agent"}  # "agent" = both agent_simple and agent_complex
REQUIRED = ("name", "version", "model_key", "cacheable", "changelog")
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


class PromptError(ValueError):
    pass


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    text: str
    model_key: str = "agent"
    cacheable: bool = True

    @property
    def hash(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()[:16]

    @property
    def tag(self) -> str:
        return f"{self.name}@{self.version}"


def _validate(name: str, meta: dict[str, Any]) -> None:
    missing = [k for k in REQUIRED if k not in meta]
    if missing:
        raise PromptError(f"prompt {name}: front-matter lacks {missing}")
    if meta["name"] != name:
        raise PromptError(f"prompt {name}: front-matter name {meta['name']!r} != file name")
    if not SEMVER.match(str(meta["version"])):
        raise PromptError(f"prompt {name}: version {meta['version']!r} is not semver")
    key = meta["model_key"]
    if key not in MODEL_KEYS:
        raise PromptError(f"prompt {name}: unknown model_key {key!r}")
    if key != "agent":  # effort/max_tokens, when stated, must agree with the pinned registry
        spec = spec_for(key)
        if "effort" in meta and meta["effort"] != spec.effort:
            raise PromptError(f"prompt {name}: effort {meta['effort']} != registry {spec.effort}")
        if "max_tokens" in meta and int(meta["max_tokens"]) != spec.max_tokens:
            raise PromptError(f"prompt {name}: max_tokens != registry {spec.max_tokens}")


def split_front_matter(raw: str, name: str) -> tuple[dict[str, Any], str]:
    if not raw.startswith("---\n"):
        raise PromptError(f"prompt {name} has no front-matter")
    _, front, body = raw.split("---\n", 2)
    meta = yaml.safe_load(front) or {}
    if not isinstance(meta, dict):
        raise PromptError(f"prompt {name}: front-matter is not a mapping")
    return meta, body.strip()


@functools.cache
def load_prompt(name: str) -> Prompt:
    raw = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    meta, body = split_front_matter(raw, name)
    _validate(name, meta)
    return Prompt(
        name=name,
        version=str(meta["version"]),
        text=body,
        model_key=str(meta["model_key"]),
        cacheable=bool(meta["cacheable"]),
    )


def all_prompts() -> list[Prompt]:
    return [load_prompt(p.stem) for p in sorted(PROMPTS_DIR.glob("*.md"))]


@functools.cache
def _tenant_template() -> jinja2.Template:
    env = jinja2.Environment(
        undefined=jinja2.StrictUndefined,
        autoescape=False,  # noqa: S701 — plain-text prompt, never rendered as HTML
        keep_trailing_newline=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    raw = (PROMPTS_DIR / "tenant_block.md.j2").read_text(encoding="utf-8")
    _, body = split_front_matter(raw, "tenant_block")
    return env.from_string(body)


def render_tenant_block(data: dict[str, Any]) -> str:
    """Institution profile block (system[1], cached per institution). Deterministic: dict keys
    are sorted by the template (`dictsort`), and callers must not pass timestamps."""
    return _tenant_template().render(**data).strip()


def tenant_block_version() -> str:
    raw = (PROMPTS_DIR / "tenant_block.md.j2").read_text(encoding="utf-8")
    meta, _ = split_front_matter(raw, "tenant_block")
    return str(meta["version"])
