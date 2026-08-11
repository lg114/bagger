"""Batch embedding + incremental backfill for ``memory_records``.

Orchestrates the Embedder (remote / fake) against the vector store:
discovers records lacking a current vector (by ``content_hash``), embeds them
in batches, and persists normalized vectors. Also owns the ``memory_fts``
rebuild so the BM25 half of hybrid search stays in sync with the source table.
"""

from __future__ import annotations

import hashlib

from bagger.config import settings
from bagger.embedding.base import Embedder
from bagger.storage.base import VectorItem


class EmbedService:
    """Backfill + maintain embeddings for one owner type (default ``memory``)."""

    def __init__(self, storage, embedder: Embedder, owner_type: str = "memory"):
        self.storage = storage
        self.embedder = embedder
        self.owner_type = owner_type
        self.model = embedder.model_name

    def backfill(self, batch_size: int | None = None, reindex_fts: bool = True) -> dict:
        """Embed every pending record and persist vectors.

        Returns a summary dict: ``{embedded, pending_total, model, dim, stats}``.
        """
        bs = batch_size or settings.embedding_batch_size
        if reindex_fts:
            self.storage.reindex_memory_fts()

        pending = self.storage.pending_for_embedding(self.owner_type, self.model)
        embedded = 0
        for i in range(0, len(pending), bs):
            chunk = pending[i : i + bs]
            # Fuse content + topics so the vector sees both the prose and the
            # keyword labels the consolidator extracted.
            texts = [f"{p['content']} {p['topics']}" for p in chunk]
            vecs = self.embedder.embed_documents(texts)
            items = []
            for p, vec in zip(chunk, vecs, strict=True):
                content = p["content"] or ""
                # Remote embedders infer dim on first call; fall back to the
                # actual returned length so the stored ``dim`` is always correct.
                dim = self.embedder.dim or len(vec)
                items.append(
                    VectorItem(
                        owner_type=self.owner_type,
                        owner_id=str(p["id"]),
                        model=self.model,
                        dim=dim,
                        vector=vec,
                        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    )
                )
            self.storage.upsert_vectors(items)
            embedded += len(items)

        stats = self.storage.vector_stats()
        return {
            "embedded": embedded,
            "pending_total": len(pending),
            "model": self.model,
            "dim": stats["dim"],
            "stats": stats,
        }

    def reindex_fts(self) -> int:
        """Rebuild the ``memory_fts`` table from all memory records."""
        return self.storage.reindex_memory_fts()
