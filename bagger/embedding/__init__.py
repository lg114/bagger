"""Embedding backend factory — mirrors ``create_llm_client`` in consolidation."""

from __future__ import annotations

import os

from bagger.config import settings
from bagger.embedding.base import Embedder
from bagger.embedding.fake import FakeEmbedder
from bagger.embedding.remote import RemoteEmbedder


def create_embedder(
    provider: str | None = None,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> Embedder:
    """Build an ``Embedder``.

    Resolution order for each setting: explicit arg → ``BAGGER_EMBEDDING_*`` env
    var → ``settings.embedding_*``. ``provider="fake"`` returns the offline hash
    embedder regardless of credentials, for tests and offline smoke tests.
    """
    provider = (
        provider or os.environ.get("BAGGER_EMBEDDING_PROVIDER") or settings.embedding_provider
    )
    if provider == "fake":
        # Fake vectors live in their own "fake" bucket so they never collide with
        # real model vectors in the embeddings table.
        return FakeEmbedder(model=model or "fake")

    base_url = (
        base_url or os.environ.get("BAGGER_EMBEDDING_BASE_URL") or settings.embedding_base_url
    )
    api_key = (
        api_key
        or os.environ.get("BAGGER_EMBEDDING_API_KEY")
        or settings.embedding_api_key
        or settings.llm_api_key
        or os.environ.get("BAGGER_LLM_API_KEY")
    )
    model = model or os.environ.get("BAGGER_EMBEDDING_MODEL") or settings.embedding_model
    return RemoteEmbedder(base_url, api_key, model)
