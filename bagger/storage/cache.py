"""Process-wide TTL cache for expensive, eventually-consistent read aggregates.

Used by the stats/health endpoints so a hot monitoring poller does not recompute
full-table aggregates on every hit. A short TTL bounds staleness: the watcher
appends events incrementally, so cached counts may lag by at most a few seconds —
acceptable for a dashboard / health view.

The cache is intentionally *process-global* (module-level). Storage connections
are opened per-request (see ``bagger.api.dependencies.get_storage``), so a cache
kept inside a single repo instance would never survive across requests; a shared
module-level store is what makes the cache effective.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

_lock = threading.Lock()
_store: dict[str, tuple[float, Any]] = {}


def ttl_get[T](key: str, ttl: float, compute: Callable[[], T]) -> T:
    """Return the cached value for ``key``, recomputing lazily if absent or stale.

    ``ttl`` is in seconds. ``compute`` is only invoked on a miss (or when the
    cached entry has expired), so a busy endpoint that shares a key pays the
    aggregate cost at most once per ``ttl`` window.
    """
    now = time.monotonic()
    with _lock:
        item = _store.get(key)
        if item is not None and now < item[0]:
            return item[1]
    value = compute()
    with _lock:
        _store[key] = (now + ttl, value)
    return value


def invalidate(key: str | None = None) -> None:
    """Drop a single cached entry, or the whole cache if ``key`` is None.

    Call after a bulk sync if you want dashboards to reflect new data instantly
    instead of waiting out the TTL.
    """
    with _lock:
        if key is None:
            _store.clear()
        else:
            _store.pop(key, None)
