"""Embedder abstraction for semantic retrieval.

Mirrors the ``LLMClient`` Protocol pattern: consumers depend on the
``Embedder`` Protocol, never on a concrete backend. Two backends ship:
``RemoteEmbedder`` (OpenAI-compatible /embeddings API) and ``FakeEmbedder``
(deterministic hash vectors, zero-dependency, for tests / offline smoke).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    """Anything that turns text into fixed-dimensional vectors."""

    model_name: str
    """Identifier of the model; also used as the ``embeddings.model`` key."""

    dim: int
    """Vector dimensionality. For remote backends this stays ``0`` until the
    first call, after which it is inferred from the API response."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of passages. Returns one vector per input."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a single search query.

        Callers MUST use this (not ``embed_documents([text])[0]``) because some
        models require a special query prefix — the asymmetry is locked inside
        the implementation so it can never be applied to the wrong side.
        """
        ...
