"""Deterministic, offline embedding for tests and spend-free dev: feature-hashed bag of normalized
words + character trigrams, L2-normalized. Not semantic, but similar strings land close — enough
for pipeline tests and for the lexical-heavy seed retrieval eval."""

import hashlib
import math

from app.kb.text import normalize, words
from app.models.kb import EMBEDDING_DIM


def _bucket(feature: str, dim: int) -> tuple[int, float]:
    digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return value % dim, (1.0 if (value >> 63) & 1 else -1.0)


class FakeProvider:
    name = "fake-hash-v1"
    dim = EMBEDDING_DIM

    async def embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for w in words(text):
            idx, sign = _bucket("w:" + w, self.dim)
            vec[idx] += 2.0 * sign
        norm_text = normalize(text)
        for i in range(len(norm_text) - 2):
            tri = norm_text[i : i + 3]
            if not tri.isspace():
                idx, sign = _bucket("t:" + tri, self.dim)
                vec[idx] += 0.5 * sign
        length = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / length for v in vec]
