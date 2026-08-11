"""Deterministic, zero-dependency embedder for tests and offline smoke.

Not semantically meaningful — it is a bag-of-words hashing of tokens into
``dim`` buckets, L2-normalized. But it is deterministic and share-vocabulary
aware: identical text yields an identical vector, and two texts sharing many
tokens yield a higher cosine than two disjoint texts. That is exactly enough
to exercise the full backfill → index → search → RRF pipeline end-to-end with
no network call and no model download.
"""

from __future__ import annotations

import hashlib
import math
import re

from bagger.embedding.base import Embedder


class FakeEmbedder(Embedder):
    """Hash-based stand-in embedder (offline / CI safe)."""

    def __init__(self, model: str = "fake", dim: int = 64):
        self.model_name = model
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in re.findall(r"\w+", text.lower()):
            h = int.from_bytes(hashlib.sha256(tok.encode("utf-8")).digest()[:4], "big")
            v[h % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)
