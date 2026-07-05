"""FastAPI dependency injection — provides database connections per request."""

from collections.abc import Generator
from contextlib import contextmanager

from bagger.config import settings
from bagger.storage.sqlite import SqliteStorage


@contextmanager
def get_storage() -> Generator[SqliteStorage, None, None]:
    """Context manager that yields a connected SqliteStorage instance."""
    storage = SqliteStorage(settings.db_path)
    storage.connect()
    try:
        yield storage
    finally:
        storage.close()
