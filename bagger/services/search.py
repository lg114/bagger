"""Full-text search service (FTS5 with BM25 ranking)."""

from bagger.storage.base import SearchIndex


def search_events(
    storage: SearchIndex,
    query: str,
    session_id: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Search events via FTS5 with BM25 ranking and snippet highlighting.

    Falls back to LIKE if FTS5 table is unavailable.
    """
    return storage.search(query, session_id=session_id, limit=limit)
