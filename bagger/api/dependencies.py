"""FastAPI dependency injection — provides database connections per request."""

from collections.abc import Generator
from contextlib import contextmanager

from bagger.storage import Storage, create_storage


@contextmanager
def get_storage() -> Generator[Storage, None, None]:
    """Context manager that yields a connected Storage instance."""
    storage = create_storage()
    try:
        yield storage
    finally:
        storage.close()
