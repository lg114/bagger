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
    result: dict | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class ScanStateStore:
    """Thread-safe holder for the most recent background scan's status."""

    def __init__(self) -> None:
        self._status = ScanSnapshot()
        self._lock = threading.Lock()

    def get(self) -> dict:
        with self._lock:
            return {
                "running": self._status.running,
                "done": self._status.done,
                "result": self._status.result,
                "error": self._status.error,
                "started_at": self._status.started_at,
                "finished_at": self._status.finished_at,
            }

    def mark_running(self) -> None:
        """A new scan started; clear any previous result."""
        with self._lock:
            self._status = ScanSnapshot(running=True, started_at=_now())

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
