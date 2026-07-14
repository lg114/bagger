"""GET /api/stats — aggregate statistics and time-series data."""

from fastapi import APIRouter, Query

from bagger.api.dependencies import get_storage

router = APIRouter()


@router.get("/stats")
def get_stats() -> dict:
    """Aggregate statistics: event counts, role distribution, token totals."""
    with get_storage() as storage:
        s = storage.get_stats()
    return {
        "total_sessions": s["total_sessions"],
        "total_events": s["total_events"],
        "user_events": s["user_events"],
        "assistant_events": s["assistant_events"],
        "tool_uses": s["tool_uses"],
        "total_tokens": s["total_tokens"],
        "cache_hit_rate": s.get("cache_hit_rate"),
        "per_model": s.get("per_model", []),
        "per_provider": s.get("per_provider", []),
    }


@router.get("/stats/daily")
def get_daily_stats(
    days: int = Query(30, ge=1, le=365, description="Number of days to include"),
) -> dict:
    """Daily event and token counts for charting."""
    with get_storage() as storage:
        rows = storage.get_daily_stats(days=days)
    return {"data": rows, "meta": {"days": days}}


@router.get("/stats/tools")
def get_tool_usage(
    limit: int = Query(15, ge=1, le=100, description="Max tools to return"),
) -> dict:
    """Most frequently used tools."""
    with get_storage() as storage:
        rows = storage.get_tool_usage_stats(limit=limit)
    return {"data": rows, "meta": {"limit": limit}}
