"""Hybrid retrieval: fuse vector (semantic) + FTS (BM25) via Reciprocal Rank Fusion.

Why RRF and not a weighted score? BM25 scores are unbounded negatives (smaller =
more relevant) while cosine lives in [-1, 1]; normalizing either for a weighted
sum is unstable and needs per-corpus tuning. RRF uses only *ranks*::

    score(d) = Σ_i  1 / (k + rank_i(d))      k = 60

No normalization, no tuning, immune to score outliers. It is the industrial
default for hybrid search.
"""

from __future__ import annotations

from bagger.embedding.base import Embedder

RRF_K = 60


class HybridSearch:
    """Semantic + lexical retrieval over ``memory_records``."""

    def __init__(self, storage, embedder: Embedder):
        self.storage = storage
        self.embedder = embedder
        self.model = embedder.model_name

    def search(
        self,
        query: str,
        mode: str = "hybrid",
        limit: int = 10,
        source: str | None = None,
    ) -> list[dict]:
        """Return ranked memory records.

        ``mode`` is one of ``hybrid`` (vector ∪ FTS fused), ``vector`` (semantic
        only), ``fts`` (BM25 only). Each result dict carries ``fused_score``.
        """
        if mode not in ("hybrid", "vector", "fts"):
            raise ValueError(f"unknown mode: {mode!r}")

        vec_ranked: list[tuple[int, int]] = []
        fts_ranked: list[tuple[int, int]] = []

        if mode in ("hybrid", "vector"):
            qv = self.embedder.embed_query(query)
            vec = self.storage.search_memory_vectors(qv, self.model, limit=limit * 2, source=source)
            vec_ranked = [(int(d["owner_id"]), i + 1) for i, d in enumerate(vec)]

        if mode in ("hybrid", "fts"):
            fts = self.storage.search_memory_fts(query, limit=limit * 2, source=source)
            fts_ranked = [(int(r["id"]), i + 1) for i, r in enumerate(fts)]

        if mode == "vector":
            fused = {mid: 1.0 / (RRF_K + rank) for mid, rank in vec_ranked}
        elif mode == "fts":
            fused = {mid: 1.0 / (RRF_K + rank) for mid, rank in fts_ranked}
        else:  # hybrid
            fused: dict[int, float] = {}
            for mid, rank in vec_ranked:
                fused[mid] = fused.get(mid, 0.0) + 1.0 / (RRF_K + rank)
            for mid, rank in fts_ranked:
                fused[mid] = fused.get(mid, 0.0) + 1.0 / (RRF_K + rank)

        ranked = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        ids = [mid for mid, _ in ranked]
        meta = {r["id"]: r for r in self.storage.get_memory_records(ids)}

        results = []
        for mid, score in ranked:
            row = dict(meta.get(mid, {}))
            row["fused_score"] = round(score, 6)
            results.append(row)
        return results
