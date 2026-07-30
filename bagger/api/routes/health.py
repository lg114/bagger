"""GET /api/health — database status and FTS5 state."""

from fastapi import APIRouter

from bagger import __version__
from bagger.api.dependencies import get_storage
from bagger.storage.cache import ttl_get

router = APIRouter()


@router.get("/health")
def health_check() -> dict:
    """Return database health status, event/session counts, and FTS state."""
    with get_storage() as storage:
        # Shares the /stats cache key (scoped by db path) so a busy poller
        # doesn't double-compute.
        stats = ttl_get(f"stats:get_stats:{storage.db_path}", 5.0, storage.get_stats)
        fts_enabled = storage.fts_enabled()
        return {
            "status": "ok",
            "sessions_count": stats["total_sessions"],
            "events_count": stats["total_events"],
            "fts_enabled": fts_enabled,
            "version": __version__,
        }
