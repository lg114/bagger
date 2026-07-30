"""FastAPI dependency injection — provides a database connection per request.

bagger opens a NEW ``SqliteStorage`` connection for every HTTP request. SQLite
connections are not safe to share across threads, and FastAPI runs sync
endpoints in a threadpool — a single shared connection could be read and
written by concurrent requests simultaneously and corrupt state. Under WAL +
``PRAGMA busy_timeout`` (set in ``SqliteStorage.connect``) separate connections
safely support concurrent readers and one writer on the same database file, so
per-request connections are both correct and cheap (the DB is a local file,
opened in microseconds).
"""

from collections.abc import Generator
from contextlib import contextmanager

from bagger.storage import Storage, create_storage


@contextmanager
def get_storage() -> Generator[Storage, None, None]:
    """Yield a connected Storage instance for the current request.

    A fresh connection is opened and closed around the request. WAL mode plus
    ``busy_timeout`` (set in ``SqliteStorage.connect``) let concurrent requests
    proceed without a shared connection or explicit cross-request locking.
    """
    storage = create_storage()
    try:
        yield storage
    finally:
        storage.close()
