"""GET /api/health — database status and FTS5 state."""

from fastapi import APIRouter

from bagger.api.dependencies import get_storage

router = APIRouter()


@router.get("/health")
def health_check() -> dict:
    """Return database health status, event/session counts, and FTS state."""
    with get_storage() as storage:
        stats = storage.get_stats()
        fts_enabled = storage.fts_enabled()
        return {
            "status": "ok",
            "sessions_count": stats["total_sessions"],
            "events_count": stats["total_events"],
            "fts_enabled": fts_enabled,
            "version": "0.2.0",
        }
