"""Versioned prompt files (`app/prompts/*.md` with YAML front-matter `version`). Changing a prompt
is a release (PLAN §12). Step 3.2 adds the agent prompts; this loader is shared."""

import functools
import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

PROMPTS_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    text: str

    @property
    def hash(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()[:16]


@functools.cache
def load_prompt(name: str) -> Prompt:
    raw = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    if not raw.startswith("---\n"):
        raise ValueError(f"prompt {name} has no front-matter")
    _, front, body = raw.split("---\n", 2)
    meta = yaml.safe_load(front) or {}
    if "version" not in meta:
        raise ValueError(f"prompt {name} front-matter lacks `version`")
    return Prompt(name=name, version=str(meta["version"]), text=body.strip())
