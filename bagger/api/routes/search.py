"""GET /api/search — FTS5 full-text search with snippet highlighting and pagination."""

from fastapi import APIRouter, Query

from bagger.api.dependencies import get_storage

router = APIRouter()


@router.get("/search")
def search_events(
    q: str = Query(..., min_length=1, description="Search query"),
    session_id: str = Query(None, description="Filter by session ID"),
    source: str = Query(None, description="Filter by originating AI tool (e.g. claude, codex)"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Results per page"),
) -> dict:
    """Full-text search across all conversation events.

    Queries run as FTS5 ``MATCH`` queries ranked by BM25, with snippet
    highlighting. CJK queries are pre-tokenized with jieba before ``MATCH`` —
    SQLite's ``unicode61`` tokenizer does not split Han/Kana/Hangul on its own.
    When jieba is missing the query is matched untokenized and CJK searches
    return no results at all; that is not a LIKE fallback, see
    ``bagger.cjk.JIEBA_CJK_WARNING``. LIKE is used only when the FTS5 table is
    absent.

    Results carry a `source` field so the UI can badge each event with its
    originating tool, and `source=` scopes the search to one tool.
    """
    with get_storage() as storage:
        result = storage.search_paginated(
            q, session_id=session_id, source=source, page=page, per_page=per_page
        )
    return result
