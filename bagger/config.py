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
