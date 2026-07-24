"""FastAPI dependency injection — provides the database connection.

The running app opens a single Storage connection once (see the ``lifespan``
in ``bagger.api.app``) and registers it via :func:`set_shared_storage`. Request
handlers then reuse that one connection instead of reconnecting on every
request — the per-request open/close cost is eliminated.

The shared instance is owned by the lifespan: it is opened at startup and
closed on shutdown. :func:`get_storage` yields it WITHOUT closing it.
"""

from collections.abc import Generator
from contextlib import contextmanager

from bagger.storage import Storage, create_storage

# App-lifetime shared connection, set by the FastAPI lifespan and cleared on
# shutdown. ``None`` means "no shared instance yet" — in which case
# :func:`get_storage` transparently falls back to a per-request connection so
# unit tests that drive the app without starting the lifespan keep working.
_shared_storage: Storage | None = None


def set_shared_storage(storage: Storage | None) -> None:
    """Register (or clear) the app-lifetime shared Storage instance."""
    global _shared_storage
    _shared_storage = storage


@contextmanager
def get_storage() -> Generator[Storage, None, None]:
    """Yield a connected Storage instance for the current request.

    In the running app the lifespan sets a single shared instance, so this
    yields that connection without opening/closing it per request. When no
    shared instance is registered (e.g. unit tests that don't start the app
    lifespan) it falls back to creating a fresh connection and closing it on
    exit — preserving the historical per-request behavior.
    """
    storage = _shared_storage
    if storage is not None:
        yield storage
        return

    # Fallback (no lifespan): ephemeral connection, closed after the request.
    ephemeral = create_storage()
    try:
        yield ephemeral
    finally:
        ephemeral.close()
