"""Centralized configuration via pydantic + optional ~/.bagger/config.toml.

Usage::

    from bagger.config import settings

    storage = SqliteStorage(settings.db_path)
    state_path = settings.state_path
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field


class Settings(BaseModel):
    """All bagger paths and runtime options, with sensible defaults.

    Override by creating ``~/.bagger/config.toml``.  Only keys you want to
    change need to be present — everything else falls back to the defaults
    below.
    """

    model_config = {"frozen": True}  # singleton-adjacent: no mutations after creation

    bagger_dir: Path = Field(default_factory=lambda: Path.home() / ".bagger")
    """Root directory for bagger data (db, state, exports, config)."""

    parser_source: str = "claude"
    """Default AI tool source for scan / watch commands."""

    source_alias: dict[str, str] = Field(default_factory=dict)
    """Map a model name (or lowercased substring) to a provider label.

    Provider detection from the model name is only a heuristic — a proxy that
    spoofs the model name (e.g. a MiMo backend served as ``claude-*``) would be
    mislabeled. Register an explicit override here to fix it::

        source_alias = {"claude-foo-proxy": "anthropic"}

    Checked before the keyword heuristic in
    ``bagger.parsers.claude._resolve_provider``.
    """

    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:8723",
            "http://localhost:8723",
        ]
    )
    """Allowed CORS origins for the REST API.

    Defaults to loopback only. This is deliberately NOT a wildcard: the API
    can trigger real file scans (``POST /api/scan``), so an open CORS policy
    would let any website drive the user's local agent. Override in
    ``~/.bagger/config.toml`` only to whitelist origins you trust.
    """

    # ── Consolidation / LLM (phase-1 structured memory extraction) ──
    # One OpenAI-compatible client covers every domestic provider (智谱 GLM,
    # DeepSeek, 阿里百炼, 硅基流动, 火山, Kimi) plus OpenAI itself. Defaults
    # point at 智谱 GLM-4-Flash, which is permanently free for personal use.
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    """OpenAI-compatible base URL for the consolidation LLM."""
    llm_model: str = "glm-4-flash"
    """Model name for consolidation extraction."""
    llm_api_key: str | None = None
    """API key; if None, falls back to the BAGGER_LLM_API_KEY env var."""

    # ── Embedding (semantic / vector retrieval) ──
    # One OpenAI-compatible /embeddings endpoint covers 智谱 embedding-3, OpenAI
    # text-embedding-3, DeepSeek, 硅基流动, etc. Defaults point at 智谱, which
    # already holds the consolidation LLM key — so no extra secret to provision.
    # ``provider`` selects the backend: ``remote`` (network API) or ``fake``
    # (deterministic hash vectors, zero-dependency, for tests/offline smoke).
    embedding_provider: str = "remote"
    """Backend for embedding vectors: ``remote`` or ``fake``."""
    embedding_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    """OpenAI-compatible base URL for the embedding endpoint."""
    embedding_api_key: str | None = None
    """Embedding API key; resolves via ``BAGGER_EMBEDDING_API_KEY`` / ``llm_api_key``."""
    embedding_model: str = "embedding-3"
    """Model name sent to the embedding endpoint (remote) or label for fake."""
    embedding_batch_size: int = 32
    """Max texts per embedding request (remote API batches)."""

    # ── Derived paths (properties so they always reflect bagger_dir) ──

    @property
    def db_path(self) -> Path:
        return self.bagger_dir / "bagger.db"

    @property
    def state_path(self) -> Path:
        return self.bagger_dir / "state.json"

    @property
    def jsonl_path(self) -> Path:
        return self.bagger_dir / "events.jsonl"

    @property
    def config_path(self) -> Path:
        return self.bagger_dir / "config.toml"


@lru_cache(maxsize=1)
def _load_settings() -> Settings:
    """Load settings from ~/.bagger/config.toml, falling back to defaults."""
    config_path = Path.home() / ".bagger" / "config.toml"
    if config_path.exists():
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
        # Convert plain strings back to Path objects if they were overridden
        for key in ("bagger_dir",):
            if key in data:
                data[key] = Path(data[key])
        return Settings(**data)
    return Settings()


# Module-level singleton — reuse everywhere.  LRU-cached so the file is
# only read once per process.
settings = _load_settings()
