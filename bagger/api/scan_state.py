"""In-memory status for background scans.

``POST /api/scan`` (and ``/api/scan/full``) run ``scan_all`` as a FastAPI
``BackgroundTask`` so the HTTP request returns immediately; the long-running
scan publishes its progress here. The UI polls ``GET /api/scan/status`` and
renders the final stats when the scan completes.

This is intentionally a single-process, in-memory store. bagger's API runs as a
single uvicorn worker (see ``sidecar_main`` / ``cli serve``), so a module-level
singleton is sufficient — there is no need for Redis or a database-backed queue
for a local, single-user tool.
"""

import threading
from dataclasses import dataclass
from datetime import UTC, datetime


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class ScanSnapshot:
    running: bool = False
    done: bool = False
    full: bool = False
    result: dict | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class ScanStateStore:
    """Thread-safe holder for the most recent background scan's status.

    A single-process, in-memory store. bagger's API runs as one uvicorn worker
    (see ``cli serve`` / sidecar), so a module-level singleton is sufficient —
    no Redis or DB-backed queue needed for a local, single-user tool.

    The store also owns the in-process scan lock: ``try_acquire`` atomically
    claims the single scan slot so concurrent ``POST /api/scan`` calls cannot
    launch overlapping scans that race on the database / watch state.
    """

    def __init__(self) -> None:
        self._status = ScanSnapshot()
        self._lock = threading.Lock()

    def get(self) -> dict:
        with self._lock:
            return {
                "running": self._status.running,
                "done": self._status.done,
                "full": self._status.full,
                "result": self._status.result,
                "error": self._status.error,
                "started_at": self._status.started_at,
                "finished_at": self._status.finished_at,
            }

    def is_running(self) -> bool:
        with self._lock:
            return self._status.running

    def try_acquire(self, full: bool) -> bool:
        """Atomically claim the single scan slot.

        Returns ``True`` (and marks the scan running) if no scan was in flight,
        so the caller may launch it. Returns ``False`` if a scan is already
        running — the caller should treat that as "reuse the current task"
        (poll ``GET /api/scan/status``) rather than starting a duplicate.

        Claiming happens at trigger time (not inside the background task) so
        two near-simultaneous requests can't both pass an ``is_running`` check
        and then both call ``mark_running`` — the lock makes the decision atomic.
        """
        with self._lock:
            if self._status.running:
                return False
            self._status = ScanSnapshot(running=True, full=full, started_at=_now())
            return True

    def mark_done(self, result: dict) -> None:
        with self._lock:
            self._status.running = False
            self._status.done = True
            self._status.result = result
            self._status.finished_at = _now()

    def mark_error(self, error: str) -> None:
        with self._lock:
            self._status.running = False
            self._status.done = True
            self._status.error = error
            self._status.finished_at = _now()


# Single-process singleton shared by the request handlers and the background task.
scan_state = ScanStateStore()
