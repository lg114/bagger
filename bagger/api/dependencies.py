"""FastAPI dependency injection — provides database connections per request."""

from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from bagger.storage.sqlite import SqliteStorage

# Default database path — matches CLI default (~/.bagger/bagger.db)
DB_PATH = Path.home() / ".bagger" / "bagger.db"


@contextmanager
def get_storage() -> Generator[SqliteStorage, None, None]:
    """Context manager that yields a connected SqliteStorage instance."""
    storage = SqliteStorage(DB_PATH)
    storage.connect()
    try:
        yield storage
    finally:
        storage.close()
