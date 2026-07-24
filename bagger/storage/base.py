"""Repository protocols — services depend on these, not on concrete storage."""

from typing import Protocol, runtime_checkable

from bagger.models.event import MemoryEvent, Session


@runtime_checkable
class SessionRepository(Protocol):
    """Session lifecycle: list, upsert, lookup."""

    def upsert_session(self, session: Session) -> None: ...
    def session_exists(self, session_id: str) -> bool: ...
    def get_session(self, session_id: str) -> dict | None: ...
    def find_session_by_prefix(self, prefix: str) -> dict | None: ...
    def list_sessions(self, limit: int = 50) -> list[dict]: ...
    def list_sessions_paginated(
        self,
        page: int = 1,
        per_page: int = 50,
        sort: str = "last_message_at",
        order: str = "desc",
        project: str | None = None,
    ) -> dict: ...
    def get_event_count(self, session_id: str) -> int: ...


@runtime_checkable
class EventRepository(Protocol):
    """Event storage + analytics."""

    def insert_event(self, event: MemoryEvent) -> None: ...
    def insert_events(self, events: list[MemoryEvent]) -> int: ...
    def upsert_event_edges(self, events: list[MemoryEvent]) -> None: ...
    def get_session_events(self, session_id: str, context: int = 0) -> list[dict]: ...
    def get_event_edges(self, session_id: str) -> list[dict]: ...
    def get_session_tree(self, session_id: str) -> list[dict]: ...
    def reconcile_event_edges(self) -> dict: ...
    def get_stats(self) -> dict: ...
    def get_daily_stats(self, days: int = 30) -> list[dict]: ...
    def get_tool_usage_stats(self, limit: int = 20) -> list[dict]: ...
    def check_integrity(self) -> list[dict]: ...


@runtime_checkable
class SearchIndex(Protocol):
    """Full-text search across events."""

    def search(self, query: str, session_id: str | None = None, limit: int = 20) -> list[dict]: ...
    def search_paginated(
        self,
        query: str,
        session_id: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict: ...
    def search_fts(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 20,
        page: int = 1,
    ) -> dict: ...
    def rebuild_fts_index(self) -> int: ...
    def fts_enabled(self) -> bool: ...

    """Whether the FTS5 virtual table exists. Public: consumed by health/doctor."""


@runtime_checkable
class Storage(SessionRepository, EventRepository, SearchIndex, Protocol):
    """Combined storage — a single backend that handles sessions, events, and search.

    SqliteStorage satisfies this structurally. Split sub-protocols above exist
    for consumers that only need a subset (e.g. search service only needs SearchIndex).
    """

    def connect(self) -> None:
        """Open the underlying connection (file, socket, etc.)."""
        ...

    def close(self) -> None:
        """Close the underlying connection. Safe to call multiple times."""
        ...
