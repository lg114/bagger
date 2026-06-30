"""Full-text search service (LIKE-based for MVP, FTS5 later)."""

from typing import Optional

from bagger.storage.sqlite import SqliteStorage


def search_events(
    storage: SqliteStorage,
    query: str,
    session_id: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """Search events by keyword matching in content_text."""
    return storage.search(query, session_id=session_id, limit=limit)
