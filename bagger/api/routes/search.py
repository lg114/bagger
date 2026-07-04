"""GET /api/search — FTS5 full-text search with snippet highlighting and pagination."""

from fastapi import APIRouter, Query

from bagger.api.dependencies import get_storage

router = APIRouter()


@router.get("/search")
def search_events(
    q: str = Query(..., min_length=1, description="Search query"),
    session_id: str = Query(None, description="Filter by session ID"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Results per page"),
) -> dict:
    """Full-text search across all conversation events.

    English/ASCII queries use FTS5 with BM25 ranking and snippet highlighting.
    CJK queries fall back to LIKE-based search.
    """
    with get_storage() as storage:
        result = storage.search_paginated(q, session_id=session_id, page=page, per_page=per_page)
    return result
