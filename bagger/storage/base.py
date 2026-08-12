"""Repository protocols — services depend on these, not on concrete storage."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from bagger.models.event import MemoryEvent, Session


@runtime_checkable
class SessionRepository(Protocol):
    """Session lifecycle: list, upsert, lookup."""

    def upsert_session(self, session: Session) -> None: ...
    def session_exists(self, session_id: str, source: str | None = None) -> bool: ...
    def get_session(self, session_id: str, source: str | None = None) -> dict | None: ...
    def find_session_by_prefix(self, prefix: str, source: str | None = None) -> dict | None: ...
    def list_sessions(self, limit: int = 50) -> list[dict]: ...
    def list_sessions_paginated(
        self,
        page: int = 1,
        per_page: int = 50,
        sort: str = "last_message_at",
        order: str = "desc",
        project: str | None = None,
        source: str | None = None,
    ) -> dict: ...
    def get_event_count(self, session_id: str, source: str | None = None) -> int: ...


@runtime_checkable
class EventRepository(Protocol):
    """Event storage + analytics."""

    def insert_event(self, event: MemoryEvent) -> None: ...
    def insert_events(self, events: list[MemoryEvent]) -> int: ...
    def upsert_event_edges(self, events: list[MemoryEvent]) -> None: ...
    def get_session_events(self, session_id: str, source: str | None = None) -> list[dict]: ...
    def get_session_events_paginated(
        self, session_id: str, page: int = 1, per_page: int = 50, source: str | None = None
    ) -> dict: ...
    def get_event_edges(self, session_id: str, source: str | None = None) -> list[dict]: ...
    def get_session_tree(self, session_id: str, source: str | None = None) -> list[dict]: ...
    def reconcile_event_edges(self) -> dict: ...
    def get_stats(self) -> dict: ...
    def get_daily_stats(self, days: int = 30) -> list[dict]: ...
    def get_tool_usage_stats(self, limit: int = 20) -> list[dict]: ...
    def check_integrity(self) -> list[dict]: ...


@runtime_checkable
class SearchIndex(Protocol):
    """Full-text search across events."""

    def search(
        self, query: str, session_id: str | None = None, limit: int = 20, source: str | None = None
    ) -> list[dict]: ...
    def search_paginated(
        self,
        query: str,
        session_id: str | None = None,
        page: int = 1,
        per_page: int = 20,
        source: str | None = None,
    ) -> dict: ...
    def search_fts(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 20,
        page: int = 1,
        source: str | None = None,
    ) -> dict: ...
    def rebuild_fts_index(self) -> int: ...
    def fts_enabled(self) -> bool: ...

    """Whether the FTS5 virtual table exists. Public: consumed by health/doctor."""


@dataclass
class VectorItem:
    """One vector to persist in the ``embeddings`` table."""

    owner_type: str
    owner_id: str
    model: str
    dim: int
    vector: list[float]
    content_hash: str


@runtime_checkable
class VectorIndex(Protocol):
    """Vector store for semantic retrieval (numpy-free; pure-Python cosine)."""

    def search_vectors(
        self,
        qv: list[float],
        owner_type: str,
        model: str,
        limit: int = 20,
        source: str | None = None,
    ) -> list[dict]:
        """Return top-``limit`` ``{owner_id, score}`` dicts by cosine similarity."""
        ...

    def upsert_vectors(self, items: list["VectorItem"]) -> int:
        """Persist normalized vectors; returns the number written."""
        ...

    def pending_for_embedding(self, owner_type: str, model: str) -> list[dict]:
        """Return ``{id, content, topics}`` rows lacking a current vector."""
        ...

    def vector_stats(self) -> dict:
        """Return ``{total, by_model, dim}`` for the embeddings table."""
        ...


@runtime_checkable
class Storage(SessionRepository, EventRepository, SearchIndex, VectorIndex, Protocol):
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

    def bulk_write(self, commit_every: int = 50) -> AbstractContextManager[None]:
        """Context manager that batches commits across many writes.

        While active, repo-level commits are deferred and flushed only every
        ``commit_every`` write units (caller invokes ``flush()`` between units,
        e.g. once per file) plus once on exit. Turns hundreds of per-file
        transactions (a large import) into a handful.

        Implementations may ignore nested bulk contexts — the outermost controls
        cadence.
        """
        ...

    def flush(self) -> None:
        """Commit point for the caller after each write unit (e.g. one file).

        Outside a ``bulk_write`` context this commits immediately (per-file
        durability for incremental watchers). Inside bulk mode it commits only
        every ``commit_every`` units, deferring the rest.
        """
        ...

    def get_memory_records(self, ids: list[int]) -> list[dict]:
        """Return memory records by id (used to hydrate retrieval results)."""
        ...

    def list_memories(
        self,
        page: int = 1,
        per_page: int = 50,
        source: str | None = None,
        type: str | None = None,
    ) -> dict:
        """Return a paginated list of memory records (the browse view).

        Optional ``source`` / ``type`` filters narrow the result set. ``topics``
        is normalized from the comma-joined DB string to a list so the shape
        matches the retrieval endpoint. Returns ``{"data": [...], "meta":
        {"page", "per_page", "total", "pages"}}``.
        """
        ...
