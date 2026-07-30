"""Tests for the process-wide TTL cache used by the stats/health endpoints."""

from bagger.storage.cache import invalidate, ttl_get


def test_ttl_get_caches_within_window_and_expires_after(monkeypatch):
    """A value is computed once per TTL window, then recomputed once expired."""
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return calls["n"]

    clock = {"t": 1000.0}
    monkeypatch.setattr("bagger.storage.cache.time.monotonic", lambda: clock["t"])
    invalidate()  # start from a clean cache

    assert ttl_get("k", 5.0, compute) == 1
    # Still inside the 5s window: served from cache, no recompute.
    assert ttl_get("k", 5.0, compute) == 1
    assert ttl_get("k", 5.0, compute) == 1
    assert calls["n"] == 1

    # Past the TTL: must recompute (and bump the counter).
    clock["t"] += 6.0
    assert ttl_get("k", 5.0, compute) == 2
    assert calls["n"] == 2

    invalidate()  # don't leak global state into other tests


def test_ttl_get_isolates_by_key(monkeypatch):
    """Distinct keys are cached independently."""
    calls = {"a": 0, "b": 0}

    def make(key):
        def compute():
            calls[key] += 1
            return key

        return compute

    clock = {"t": 2000.0}
    monkeypatch.setattr("bagger.storage.cache.time.monotonic", lambda: clock["t"])
    invalidate()

    ttl_get("a", 5.0, make("a"))
    ttl_get("b", 5.0, make("b"))
    # Re-reading each key hits the cache, not the compute fn.
    ttl_get("a", 5.0, make("a"))
    ttl_get("b", 5.0, make("b"))

    assert calls["a"] == 1
    assert calls["b"] == 1

    invalidate()
