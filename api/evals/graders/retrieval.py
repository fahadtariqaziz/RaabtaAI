"""Retrieval grader: rank of the first top-k chunk containing a gold substring; recall@k / MRR."""

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

DATASET = Path(__file__).resolve().parents[1] / "datasets" / "retrieval.yaml"
KS = (1, 3, 5)


class RetrievalCase(BaseModel):
    id: str
    institution: str
    lang: str
    query: str
    gold: list[str] = Field(min_length=1)


def load_cases(path: Path = DATASET) -> list[RetrievalCase]:
    with path.open(encoding="utf-8") as fh:
        return [RetrievalCase.model_validate(c) for c in yaml.safe_load(fh)]


def first_hit_rank(texts: list[str], gold: list[str]) -> int | None:
    for rank, text in enumerate(texts, start=1):
        if any(g in text for g in gold):
            return rank
    return None


@dataclass
class RetrievalReport:
    label: str
    ranks: dict[str, int | None] = field(default_factory=dict)  # case id -> rank
    langs: dict[str, str] = field(default_factory=dict)  # case id -> lang

    def metrics(self, lang: str | None = None) -> dict[str, float]:
        ids = [c for c in self.ranks if lang is None or self.langs[c] == lang]
        if not ids:
            return {}
        out = {
            f"recall@{k}": sum(1 for c in ids if (r := self.ranks[c]) and r <= k) / len(ids)
            for k in KS
        }
        out["mrr"] = sum(1 / r for c in ids if (r := self.ranks[c])) / len(ids)
        out["n"] = len(ids)
        return out

    def by_lang(self) -> dict[str, dict[str, float]]:
        groups: dict[str, list[str]] = defaultdict(list)
        for cid, lang in self.langs.items():
            groups[lang].append(cid)
        return {"all": self.metrics(), **{lang: self.metrics(lang) for lang in sorted(groups)}}

    def misses(self, k: int = 5) -> list[str]:
        return [c for c, r in self.ranks.items() if r is None or r > k]

    def markdown(self) -> str:
        rows = [
            f"| {name} | {m['n']:.0f} | {m['recall@1']:.2f} | {m['recall@3']:.2f} "
            f"| {m['recall@5']:.2f} | {m['mrr']:.2f} |"
            for name, m in self.by_lang().items()
        ]
        head = "| subset | n | recall@1 | recall@3 | recall@5 | MRR |\n|---|---|---|---|---|---|"
        return f"### {self.label}\n\n{head}\n" + "\n".join(rows) + "\n"
