"""Storage package — repositories, concrete implementations, and factory."""

from pathlib import Path

from bagger.storage.base import (
    EventRepository,
    SearchIndex,
    SessionRepository,
    Storage,
)
from bagger.storage.sqlite import SqliteStorage


def create_storage(db_path: Path | str | None = None) -> Storage:
    """Factory: create and connect a Storage backend.

    Returns a **connected** ``Storage`` instance. Callers MUST call
    ``.close()`` when done (use ``try/finally`` or a context manager).

    Args:
        db_path: Optional override path. When ``None``, reads from
            ``bagger.config.settings.db_path``.
    """
    from bagger.config import settings

    path = Path(db_path) if db_path is not None else settings.db_path
    storage = SqliteStorage(path)
    storage.connect()
    return storage


__all__ = [
    "SessionRepository",
    "EventRepository",
    "SearchIndex",
    "Storage",
    "SqliteStorage",
    "create_storage",
]
