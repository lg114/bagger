"""SQLite storage with FTS5 full-text search for bagger.

O V E R V I E W

``SqliteStorage`` is a facade that delegates to three inner repositories,
each operating on a shared ``sqlite3.Connection``::

    SqliteStorage (facade, implements Storage Protocol)
        ├── SqliteSessionRepository  (SessionRepository Protocol)
        ├── SqliteEventRepository    (EventRepository Protocol)
        └── SqliteSearchIndex        (SearchIndex Protocol)

All three repos are thin wrappers around ``conn.execute()`` — they do not
own the connection lifecycle. ``SqliteStorage.connect()`` creates the
connection *and* the repos; ``.close()`` tears them all down.

Module-level helpers (``_row_to_dict``, ``_extract_text``, ``contains_cjk``,
etc.) are shared across repos and remain stateless.
"""

import array
import contextlib
import hashlib
import json
import logging
import math
import sqlite3
import threading
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

from bagger.cjk import (
    _CJK_RE,
    JIEBA_CJK_WARNING,
    contains_cjk,
    jieba_available,
)
from bagger.models.event import BlockType, MemoryEvent, Session
from bagger.storage.base import VectorItem
from bagger.storage.migrations import _column_exists, apply_migrations

logger = logging.getLogger(__name__)

# ── Schema ──────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    source TEXT NOT NULL DEFAULT 'claude',
    id TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    project_path TEXT NOT NULL DEFAULT '',
    message_count INTEGER NOT NULL DEFAULT 0,
    first_message_at TEXT,
    last_message_at TEXT,
    last_synced_at TEXT,
    parent_session_id TEXT,
    resume_of TEXT,
    is_compaction INTEGER NOT NULL DEFAULT 0,
    compaction_of TEXT,
    PRIMARY KEY (source, id)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    parent_event_id TEXT,
    timestamp TEXT NOT NULL,
    role TEXT NOT NULL,
    content_json TEXT NOT NULL,
    content_text TEXT NOT NULL DEFAULT '',
    token_input INTEGER NOT NULL DEFAULT 0,
    token_output INTEGER NOT NULL DEFAULT 0,
    cwd TEXT,
    git_branch TEXT,
    model TEXT,
    token_cache_read INTEGER NOT NULL DEFAULT 0,
    token_cache_write INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL,
    currency TEXT NOT NULL DEFAULT 'USD',
    service_tier TEXT,
    provider TEXT,
    source TEXT NOT NULL DEFAULT 'claude',
    UNIQUE(source, event_id)
);

CREATE TABLE IF NOT EXISTS tool_uses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    tool_id TEXT NOT NULL DEFAULT '',
    tool_input_json TEXT NOT NULL DEFAULT '{}',
    source TEXT NOT NULL DEFAULT 'claude',
    FOREIGN KEY (source, event_id) REFERENCES events(source, event_id)
);

CREATE INDEX IF NOT EXISTS idx_tool_uses_event ON tool_uses(event_id);
CREATE INDEX IF NOT EXISTS idx_tool_uses_name ON tool_uses(tool_name);

CREATE TABLE IF NOT EXISTS event_edges (
    event_id TEXT PRIMARY KEY,
    parent_event_id TEXT,
    session_id TEXT NOT NULL,
    depth INTEGER NOT NULL DEFAULT 0,
    source TEXT,
    UNIQUE(event_id)
);

CREATE INDEX IF NOT EXISTS idx_event_edges_session ON event_edges(session_id);

-- Covering index for time-series aggregates (get_daily_stats): the GROUP BY is on
-- substr(timestamp,1,10) and the SUMs read token_input/token_output, so a single
-- index-only scan serves the dashboard query with no table lookups or temp sort.
CREATE INDEX IF NOT EXISTS idx_events_date
    ON events(substr(timestamp, 1, 10), token_input, token_output);

-- ── Phase 1: structured memory extraction (Consolidator output) ──
-- A memory_record is a durable, reusable cognitive unit distilled from raw
-- conversation events: a fact / preference / decision / lesson. It is what
-- turns bagger from a "conversation search engine" into a memory store.
CREATE TABLE IF NOT EXISTS memory_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,            -- fact / preference / decision / lesson
    content TEXT NOT NULL,         -- the distilled cognitive unit (concise)
    topics TEXT NOT NULL DEFAULT '',  -- comma-separated keywords for topic recall
    confidence REAL NOT NULL DEFAULT 0.5,  -- extraction confidence 0..1
    -- Provenance: points back to the source conversation + event.
    source TEXT NOT NULL DEFAULT 'claude',
    session_id TEXT NOT NULL,
    event_id TEXT,                 -- primary source event (nullable: a record
                                    -- may synthesize across several events)
    created_at TEXT NOT NULL,
    -- Deduplication key: type-scoped fingerprint of the normalized content
    -- (see ``bagger.textnorm.content_fingerprint``). UNIQUE below, so
    -- "one memory, many confirmations" is a database invariant rather than a
    -- Python convention that the next caller can forget.
    content_hash TEXT NOT NULL DEFAULT '',
    -- How many extractions produced this same record. Doubles as a
    -- corroboration signal: a fact confirmed across ten sessions outranks a
    -- one-off remark.
    merge_count INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT '',   -- last time it was reinforced
    -- Phase 3 (forgetting) fields — created now, used later.
    relevance REAL NOT NULL DEFAULT 1.0,
    archived INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (source, session_id) REFERENCES sessions(source, id)
);

CREATE INDEX IF NOT EXISTS idx_memory_records_type ON memory_records(type);
CREATE INDEX IF NOT EXISTS idx_memory_records_topics ON memory_records(topics);
CREATE INDEX IF NOT EXISTS idx_memory_records_session
    ON memory_records(source, session_id);
-- NOTE: the UNIQUE index on content_hash is created by the v6 migration, not
-- here. A legacy DB whose memory_records table pre-dates content_hash would skip
-- the CREATE TABLE IF NOT EXISTS above (table already exists) but then crash on
-- a CREATE INDEX referencing a column that does not exist yet — the migration
-- adds the column first, so the index must live there, not in the base SCHEMA.

-- Every (source, session, event) that confirmed a memory record. This table is
-- what makes UNIQUE(content_hash) safe: collapsing ten duplicate rows into one
-- would otherwise destroy nine provenance trails, and a memory that cannot be
-- traced back to a transcript is a rumour.
CREATE TABLE IF NOT EXISTS memory_provenance (
    record_id   INTEGER NOT NULL,
    source      TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    -- '' rather than NULL: NULLs compare distinct inside a composite primary
    -- key, so a nullable column would let the same pair be inserted twice.
    event_id    TEXT NOT NULL DEFAULT '',
    observed_at TEXT NOT NULL,
    PRIMARY KEY (record_id, source, session_id, event_id),
    FOREIGN KEY (record_id) REFERENCES memory_records(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_memory_provenance_session
    ON memory_provenance(source, session_id);

-- Incremental processing cursor: which (source, session) has been consolidated
-- up to which event id. Mirrors the WatchState (session_id -> byte_offset) idea
-- but at the event granularity, so a re-run only processes new events.
CREATE TABLE IF NOT EXISTS consolidation_state (
    source TEXT NOT NULL,
    session_id TEXT NOT NULL,
    last_event_id INTEGER NOT NULL DEFAULT 0,  -- MAX(events.id) already processed
    last_run_at TEXT NOT NULL,
    record_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (source, session_id)
);
"""

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
    content_text,
    session_id UNINDEXED,
    event_id UNINDEXED,
    source UNINDEXED,
    tokenize='unicode61'
);
"""

# ── Column lists for row→dict mapping ──────────────────────

SESSION_COLS = (
    "source, id, summary, project_path, message_count, first_message_at, last_message_at, "
    "parent_session_id, resume_of, is_compaction, compaction_of"
)

EVENT_COLS = (
    "e.id as db_id, e.event_id, e.session_id, e.source, s.summary as session_summary, "
    "e.timestamp, e.role, e.content_json, e.content_text, "
    "e.token_input, e.token_output, s.project_path"
)

EVENT_DETAIL_COLS = (
    "event_id, session_id, source, parent_event_id, timestamp, role, "
    "content_json, content_text, token_input, token_output, "
    "cwd, git_branch, model, "
    "token_cache_read, token_cache_write, cost_usd, currency, service_tier, provider"
)


def _events_contain_cjk(conn: sqlite3.Connection, limit: int = 500) -> bool:
    """Heuristic: do the first ``limit`` stored events contain CJK characters?

    Used by the jieba guard to decide whether a missing jieba install actually
    breaks search — English-only corpora don't need it. Samples the first
    ``limit`` rows instead of scanning the whole table.
    """
    try:
        rows = conn.execute(
            "SELECT content_text FROM events ORDER BY id LIMIT ?", (limit,)
        ).fetchall()
    except sqlite3.OperationalError:
        return False
    return any(contains_cjk(r[0] or "") for r in rows)


def check_jieba_cjk_coverage(conn: sqlite3.Connection) -> str | None:
    """Return a warning when jieba is unavailable but stored events contain CJK.

    Returns ``None`` when CJK search is safe (jieba present, or no CJK data),
    otherwise the warning message the caller should surface to the user.
    """
    if jieba_available() or not _events_contain_cjk(conn):
        return None
    return JIEBA_CJK_WARNING


def _escape_fts5_query(query: str) -> str:
    """Escape and format a query string for FTS5 MATCH.

    Wraps each word in double quotes with ``*`` for prefix matching
    (e.g. ``"auth"*``).  Called for both ASCII and pre-tokenized CJK queries.
    """
    query = query.strip()
    if not query:
        return '""'

    query = query.replace('"', '""')
    parts = [f'"{w}"*' if len(w) >= 2 else f'"{w}"' for w in query.split()]
    return " ".join(parts) or f'"{query}"'


def _extract_text(event: MemoryEvent) -> str:
    """Extract concatenated plain text from content blocks for FTS indexing."""
    parts: list[str] = []
    for b in event.content_blocks:
        if b.block_type in (BlockType.TEXT, BlockType.THINKING) and b.text:
            parts.append(b.text)
        elif b.block_type == BlockType.TOOL_USE:
            parts.append(f"[tool_use:{b.tool_name}]")
        elif b.block_type == BlockType.TOOL_RESULT and b.text:
            parts.append(f"[tool_result:{b.text[:200]}]")
    return " ".join(parts)


def _tokenize_for_fts(text: str) -> str:
    """Pre-tokenize CJK text with jieba so that unicode61 can index it correctly.

    Without this, ``unicode61`` treats Chinese text as one unbroken token,
    making FTS5 useless for CJK queries (falling back to LIKE full-table scans).

    In addition to jieba word tokens we also emit every individual CJK character
    as a token. CJK has no whitespace word boundaries, so a bare single-hanzi
    query (e.g. "数") would otherwise never match a multi-character word
    ("数据库") that contains it — adding char tokens gives single-character
    prefix recall. ASCII and punctuation are already handled by unicode61's
    default tokenization, so they are not duplicated here.

    Returns the input unchanged when jieba is unavailable or the text is pure ASCII.
    """
    if not text or not contains_cjk(text) or not jieba_available():
        return text
    import jieba

    tokens = list(jieba.cut(text, HMM=False))
    # Append each CJK character so a single-char query can recall any word that
    # contains it. _CJK_RE matches one CJK/Hiragana/Katakana/Hangul codepoint.
    tokens.extend(ch for ch in text if _CJK_RE.match(ch))
    return " ".join(tokens)


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a sqlite3.Row to a plain dict using column names."""
    return dict(row)


def _pagination_meta(page: int, per_page: int, total: int) -> dict:
    """Build pagination metadata dict."""
    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


# ── INSERT SQL (shared across event repo and facade) ───────

_INSERT_EVENT_SQL = """INSERT INTO events
    (event_id, session_id, parent_event_id, timestamp, role,
     content_json, content_text, token_input, token_output,
     cwd, git_branch, model,
     token_cache_read, token_cache_write, cost_usd, currency, service_tier, provider,
     source)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(source, event_id) DO UPDATE SET
        session_id=excluded.session_id,
        parent_event_id=excluded.parent_event_id,
        timestamp=excluded.timestamp,
        role=excluded.role,
        content_json=excluded.content_json,
        content_text=excluded.content_text,
        token_input=excluded.token_input,
        token_output=excluded.token_output,
        cwd=excluded.cwd,
        git_branch=excluded.git_branch,
        model=excluded.model,
        token_cache_read=excluded.token_cache_read,
        token_cache_write=excluded.token_cache_write,
        cost_usd=excluded.cost_usd,
        currency=excluded.currency,
        service_tier=excluded.service_tier,
        provider=excluded.provider,
        source=excluded.source"""


# ===================================================================
# Repository classes (thin wrappers around sqlite3.Connection)
# ===================================================================


class SqliteSessionRepository:
    """Session CRUD backed by a shared SQLite connection."""

    def __init__(self, conn: sqlite3.Connection, commit_fn):
        self._conn = conn
        self._commit = commit_fn

    def upsert_session(self, session: Session) -> None:
        self._conn.execute(
            """INSERT INTO sessions (source, id, summary, project_path, message_count,
               first_message_at, last_message_at, last_synced_at,
               parent_session_id, resume_of, is_compaction, compaction_of)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(source, id) DO UPDATE SET
               summary=excluded.summary,
               project_path=excluded.project_path,
               message_count=excluded.message_count,
               first_message_at=excluded.first_message_at,
               last_message_at=excluded.last_message_at,
               last_synced_at=excluded.last_synced_at,
               parent_session_id=excluded.parent_session_id,
               resume_of=excluded.resume_of,
               is_compaction=excluded.is_compaction,
               compaction_of=excluded.compaction_of""",
            (
                session.source,
                session.session_id,
                session.summary,
                session.project_path,
                session.message_count,
                session.first_message_at.isoformat() if session.first_message_at else None,
                session.last_message_at.isoformat() if session.last_message_at else None,
                datetime.now(UTC).isoformat(),
                session.parent_session_id,
                session.resume_of,
                int(session.is_compaction),
                session.compaction_of,
            ),
        )
        self._commit()
        # Single-point write: commit immediately so direct callers
        # (CLI, tests, one-off upserts) see their session persisted without
        # having to remember to commit. During a ``bulk_write`` context the
        # commit is deferred and flushed in batches by the caller's ``flush()``.

    def session_exists(self, session_id: str, source: str | None = None) -> bool:
        if source is not None:
            row = self._conn.execute(
                "SELECT 1 FROM sessions WHERE source = ? AND id = ?", (source, session_id)
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return row is not None

    def get_session(self, session_id: str, source: str | None = None) -> dict | None:
        if source is not None:
            row = self._conn.execute(
                f"SELECT {SESSION_COLS} FROM sessions WHERE source = ? AND id = ?",
                (source, session_id),
            ).fetchone()
        else:
            row = self._conn.execute(
                f"SELECT {SESSION_COLS} FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def find_session_by_prefix(self, prefix: str, source: str | None = None) -> dict | None:
        if source is not None:
            rows = self._conn.execute(
                f"SELECT {SESSION_COLS} FROM sessions WHERE source = ? AND id LIKE ?",
                (source, f"{prefix}%"),
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"SELECT {SESSION_COLS} FROM sessions WHERE id LIKE ?",
                (f"{prefix}%",),
            ).fetchall()
        if len(rows) == 1:
            return _row_to_dict(rows[0])
        return None

    def list_sessions(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            f"SELECT {SESSION_COLS} FROM sessions ORDER BY last_message_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    @staticmethod
    def _project_filter(project: str | None) -> tuple[str, list]:
        """Build a WHERE clause (and params) for an optional project_path filter.

        ``project`` values:
          - falsy (None/""):  no filter (all sessions)
          - "no-project":     sessions with no project_path (NULL or empty)
          - anything else:    exact ``project_path`` match
        """
        if not project:
            return "", []
        if project == "no-project":
            return " WHERE project_path IS NULL OR project_path = ''", []
        return " WHERE project_path = ?", [project]

    def list_sessions_paginated(
        self,
        page: int = 1,
        per_page: int = 50,
        sort: str = "last_message_at",
        order: str = "desc",
        project: str | None = None,
        source: str | None = None,
    ) -> dict:
        offset = (page - 1) * per_page
        allowed_sort = {"last_message_at", "message_count", "first_message_at", "id"}
        col = sort if sort in allowed_sort else "last_message_at"
        direction = "DESC" if order.lower() == "desc" else "ASC"

        where, where_params = self._project_filter(project)
        if source is not None:
            if where:
                where += " AND source = ?"
            else:
                where = " WHERE source = ?"
            where_params = [*where_params, source]

        total = self._conn.execute(
            f"SELECT COUNT(*) FROM sessions{where}", where_params
        ).fetchone()[0]
        rows = self._conn.execute(
            f"SELECT {SESSION_COLS} FROM sessions{where} "
            f"ORDER BY {col} {direction} NULLS LAST LIMIT ? OFFSET ?",
            (*where_params, per_page, offset),
        ).fetchall()

        return {
            "data": [_row_to_dict(r) for r in rows],
            "meta": _pagination_meta(page, per_page, total),
        }

    def get_event_count(self, session_id: str, source: str | None = None) -> int:
        if source is not None:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM events WHERE session_id = ? AND source = ?",
                (session_id, source),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM events WHERE session_id = ?", (session_id,)
            ).fetchone()
        return row[0] if row else 0


# ────────────────────────────────────────────────────────────


class SqliteEventRepository:
    """Event storage + stats backed by a shared SQLite connection."""

    def __init__(self, conn: sqlite3.Connection, commit_fn):
        self._conn = conn
        self._commit = commit_fn

    # -- helpers --------------------------------------------------

    @staticmethod
    def _event_params(event: MemoryEvent) -> tuple:
        """Serialize a MemoryEvent into INSERT parameter tuple."""
        content_json = json.dumps(
            [b.model_dump() for b in event.content_blocks], ensure_ascii=False
        )
        content_text = _extract_text(event)
        return (
            event.event_id,
            event.session_id,
            event.parent_event_id,
            event.timestamp.isoformat(),
            event.role.value,
            content_json,
            content_text,
            event.token_input,
            event.token_output,
            event.cwd,
            event.git_branch,
            event.model,
            event.token_cache_read,
            event.token_cache_write,
            event.cost_usd,
            event.currency,
            event.service_tier,
            event.provider,
            event.source,
        )

    def _insert_tool_uses(self, event: MemoryEvent) -> None:
        """Extract TOOL_USE blocks from an event and insert into tool_uses table.

        Uses delete-before-insert per event_id for idempotency.
        """
        rows = [
            (
                event.event_id,
                b.tool_name or "unknown",
                b.tool_id or "",
                json.dumps(b.tool_input or {}, ensure_ascii=False),
                event.source,
            )
            for b in event.content_blocks
            if b.block_type == BlockType.TOOL_USE
        ]
        if rows:
            self._conn.execute(
                "DELETE FROM tool_uses WHERE event_id = ? AND source = ?",
                (event.event_id, event.source),
            )
            self._conn.executemany(
                "INSERT INTO tool_uses(event_id, tool_name, tool_id, tool_input_json, source) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )

    def _insert_fts(self, event: MemoryEvent) -> None:
        """Insert tokenized text into the FTS5 index for this event.

        Uses delete-before-insert keyed on the composite ``(event_id, source)``
        for idempotency (same pattern as ``_insert_tool_uses``). Keying on
        ``source`` too prevents a re-scan from deleting a different tool's FTS
        row when two tools share an event uuid.
        """
        raw_text = _extract_text(event)
        fts_text = _tokenize_for_fts(raw_text)
        self._conn.execute(
            "DELETE FROM events_fts WHERE event_id = ? AND source = ?",
            (event.event_id, event.source),
        )
        self._conn.execute(
            "INSERT INTO events_fts(content_text, session_id, event_id, source) "
            "VALUES (?, ?, ?, ?)",
            (fts_text, event.session_id, event.event_id, event.source),
        )

    # -- public API -----------------------------------------------

    def insert_event(self, event: MemoryEvent) -> None:
        self._conn.execute(_INSERT_EVENT_SQL, self._event_params(event))
        self._insert_tool_uses(event)
        self._insert_fts(event)
        self._commit()

    def insert_events(self, events: list[MemoryEvent]) -> int:
        """Batch insert events + their tool_uses / FTS rows in a few statements.

        Previously each event ran its own DELETE+INSERT for ``tool_uses`` and
        ``events_fts`` (4N round-trips for N events). We now collect all rows
        and issue a single ``executemany`` per table, then commit once — roughly
        4N → 3 statements for a large import. The deletes key on the composite
        ``(event_id, source)`` so two tools sharing a uuid stay isolated.
        Returns the count of new events inserted.
        """
        params = [self._event_params(e) for e in events]
        before = self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        self._conn.executemany(_INSERT_EVENT_SQL, params)

        tu_rows: list[tuple] = []
        fts_rows: list[tuple] = []
        for e in events:
            for b in e.content_blocks:
                if b.block_type == BlockType.TOOL_USE:
                    tu_rows.append(
                        (
                            e.event_id,
                            b.tool_name or "unknown",
                            b.tool_id or "",
                            json.dumps(b.tool_input or {}, ensure_ascii=False),
                            e.source,
                        )
                    )
            fts_rows.append(
                (
                    _tokenize_for_fts(_extract_text(e)),
                    e.session_id,
                    e.event_id,
                    e.source,
                )
            )

        if tu_rows:
            self._conn.executemany(
                "DELETE FROM tool_uses WHERE event_id = ? AND source = ?",
                [(r[0], r[4]) for r in tu_rows],
            )
            self._conn.executemany(
                "INSERT INTO tool_uses(event_id, tool_name, tool_id, tool_input_json, source) "
                "VALUES (?, ?, ?, ?, ?)",
                tu_rows,
            )
        if fts_rows:
            self._conn.executemany(
                "DELETE FROM events_fts WHERE event_id = ? AND source = ?",
                [(r[2], r[3]) for r in fts_rows],
            )
            self._conn.executemany(
                "INSERT INTO events_fts(content_text, session_id, event_id, source) "
                "VALUES (?, ?, ?, ?)",
                fts_rows,
            )
        self._commit()
        after = self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        return after - before

    def get_session_events(self, session_id: str, source: str | None = None) -> list[dict]:
        if source is not None:
            rows = self._conn.execute(
                f"SELECT {EVENT_DETAIL_COLS} FROM events "
                f"WHERE session_id = ? AND source = ? ORDER BY timestamp",
                (session_id, source),
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"SELECT {EVENT_DETAIL_COLS} FROM events WHERE session_id = ? ORDER BY timestamp",
                (session_id,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_session_events_paginated(
        self,
        session_id: str,
        page: int = 1,
        per_page: int = 50,
        source: str | None = None,
    ) -> dict:
        """Paginated events for a session (ordered by timestamp ascending).

        Caps ``per_page`` at 500 so a single request can't materialize an
        unbounded number of rows into memory / over the wire at once.
        """
        per_page = max(1, min(per_page, 500))
        offset = (max(1, page) - 1) * per_page
        if source is not None:
            total = self._conn.execute(
                "SELECT COUNT(*) FROM events WHERE session_id = ? AND source = ?",
                (session_id, source),
            ).fetchone()[0]
            rows = self._conn.execute(
                f"SELECT {EVENT_DETAIL_COLS} FROM events "
                f"WHERE session_id = ? AND source = ? ORDER BY timestamp LIMIT ? OFFSET ?",
                (session_id, source, per_page, offset),
            ).fetchall()
        else:
            total = self._conn.execute(
                "SELECT COUNT(*) FROM events WHERE session_id = ?", (session_id,)
            ).fetchone()[0]
            rows = self._conn.execute(
                f"SELECT {EVENT_DETAIL_COLS} FROM events WHERE session_id = ? "
                f"ORDER BY timestamp LIMIT ? OFFSET ?",
                (session_id, per_page, offset),
            ).fetchall()
        return {
            "data": [_row_to_dict(r) for r in rows],
            "meta": _pagination_meta(page, per_page, total),
        }

    def get_stats(self) -> dict:
        row = self._conn.execute(
            "SELECT "
            "COUNT(*) as total_events, "
            "COALESCE(SUM(token_input + token_output), 0) as total_tokens, "
            "SUM(CASE WHEN role='user' THEN 1 ELSE 0 END) as user_events, "
            "SUM(CASE WHEN role='assistant' THEN 1 ELSE 0 END) as assistant_events, "
            "COALESCE(SUM(token_cache_read), 0) as cache_read, "
            "COALESCE(SUM(token_cache_write), 0) as cache_write, "
            "COALESCE(SUM(token_input), 0) as total_input, "
            "COALESCE(SUM(cost_usd), 0) as total_cost "
            "FROM events"
        ).fetchone()
        total_sessions = self._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        tool_uses = self._conn.execute("SELECT COUNT(*) FROM tool_uses").fetchone()[0]

        cache_denom = row["cache_read"] + row["total_input"]
        cache_hit_rate = row["cache_read"] / cache_denom if cache_denom > 0 else None

        per_model = self._conn.execute(
            "SELECT model, "
            "COALESCE(SUM(token_input + token_output), 0) as tokens, "
            "COUNT(*) as events, "
            "COALESCE(SUM(cost_usd), 0) as cost "
            "FROM events WHERE model IS NOT NULL "
            "GROUP BY model ORDER BY tokens DESC LIMIT 10"
        ).fetchall()
        per_provider = self._conn.execute(
            "SELECT provider, "
            "COALESCE(SUM(token_input + token_output), 0) as tokens, "
            "COUNT(*) as events, "
            "COALESCE(SUM(cost_usd), 0) as cost "
            "FROM events WHERE provider IS NOT NULL "
            "GROUP BY provider ORDER BY tokens DESC LIMIT 10"
        ).fetchall()

        per_source = self._conn.execute(
            "SELECT source, "
            "COUNT(*) as events, "
            "COALESCE(SUM(token_input + token_output), 0) as tokens "
            "FROM events WHERE source IS NOT NULL "
            "GROUP BY source ORDER BY events DESC"
        ).fetchall()

        return {
            "total_sessions": total_sessions,
            "total_events": row["total_events"],
            "total_tokens": row["total_tokens"],
            "user_events": row["user_events"],
            "assistant_events": row["assistant_events"],
            "tool_uses": tool_uses,
            "cache_hit_rate": cache_hit_rate,
            "total_cost_usd": row["total_cost"],
            "per_model": [_row_to_dict(r) for r in per_model],
            "per_provider": [_row_to_dict(r) for r in per_provider],
            "per_source": [_row_to_dict(r) for r in per_source],
        }

    def get_daily_stats(self, days: int = 30) -> list[dict]:
        rows = self._conn.execute(
            "SELECT substr(timestamp, 1, 10) as date, "
            "COUNT(*) as count, "
            "COALESCE(SUM(token_input + token_output), 0) as tokens, "
            "COALESCE(SUM(cost_usd), 0) as cost "
            "FROM events GROUP BY date ORDER BY date DESC LIMIT ?",
            (days,),
        ).fetchall()
        return [_row_to_dict(r) for r in reversed(rows)]

    def get_tool_usage_stats(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT tool_name, COUNT(*) as count "
            "FROM tool_uses "
            "GROUP BY tool_name ORDER BY count DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def check_integrity(self) -> list[dict]:
        issues: list[dict] = []

        try:
            self._conn.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.Error as e:
            issues.append({"level": "error", "message": f"Database corrupt: {e}"})

        if self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0:
            issues.append({"level": "info", "message": "No events in database"})

        empty_sessions = self._conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE message_count = 0"
        ).fetchone()[0]
        if empty_sessions:
            issues.append(
                {"level": "warn", "message": f"{empty_sessions} sessions have 0 messages"}
            )

        return issues


# ────────────────────────────────────────────────────────────


class SqliteSearchIndex:
    """FTS5 + CJK full-text search backed by a shared SQLite connection."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    # -- routing --------------------------------------------------

    def _tokenized_fts_query(self, query: str) -> str:
        """Tokenize a CJK query with jieba so it matches FTS5 tokenized content.

        Returns the original query unchanged for ASCII-only input or when
        jieba is unavailable.
        """
        if not contains_cjk(query) or not jieba_available():
            return query
        import jieba

        return " ".join(jieba.cut(query, HMM=False))

    def search(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 20,
        source: str | None = None,
    ) -> list[dict]:
        """FTS5 with BM25 ranking; CJK queries are pre-tokenized before MATCH.

        Falls back to LIKE only when FTS5 is unavailable or jieba isn't
        installed for CJK text.
        """
        if self._fts_enabled():
            tokenized = self._tokenized_fts_query(query)
            return self.search_fts(tokenized, session_id=session_id, limit=limit, source=source)[
                "data"
            ]
        return self._search_like(query, session_id=session_id, limit=limit, source=source)

    def search_paginated(
        self,
        query: str,
        session_id: str | None = None,
        page: int = 1,
        per_page: int = 20,
        source: str | None = None,
    ) -> dict:
        """FTS5 with pre-tokenization; LIKE fallback. Paginated for API."""
        if self._fts_enabled():
            tokenized = self._tokenized_fts_query(query)
            return self.search_fts(
                tokenized, session_id=session_id, page=page, limit=per_page, source=source
            )
        return self._search_like_paginated(
            query, session_id=session_id, page=page, per_page=per_page, source=source
        )

    # -- FTS5 -----------------------------------------------------

    def _fts_enabled(self) -> bool:
        try:
            return (
                self._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='events_fts'"
                ).fetchone()
                is not None
            )
        except sqlite3.Error:
            return False

    def search_fts(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 20,
        page: int = 1,
        source: str | None = None,
    ) -> dict:
        """FTS5 full-text search with BM25 ranking and snippet generation."""
        safe_query = _escape_fts5_query(query)
        offset = (page - 1) * limit

        count_sql = "SELECT COUNT(*) FROM events_fts WHERE events_fts MATCH ?"
        count_params: list = [safe_query]
        if session_id:
            count_sql += " AND session_id = ?"
            count_params.append(session_id)
        if source:
            count_sql += " AND source = ?"
            count_params.append(source)
        total = self._conn.execute(count_sql, count_params).fetchone()[0]

        # NOTE: the JOIN must match on (source, event_id), not just event_id.
        # Under multi-source, two different tools can emit the same event uuid;
        # joining on event_id alone would cross-wire rows between sources and can
        # surface a different tool's event for a given search hit.
        #
        # bm25(events_fts) uses equal per-column weights so ranking reflects
        # content_text matches (the only indexed, searchable column). The prior
        # bm25(events_fts, 0.0, 10.0, 5.0) set the content_text (column 0) weight
        # to 0.0, so results were effectively ordered by rowid — i.e. no relevance.
        sql = (
            f"SELECT {EVENT_COLS}, "
            f"snippet(events_fts, 0, '<mark>', '</mark>', '...', 32) as snippet, "
            f"bm25(events_fts) as rank "
            f"FROM events_fts fts "
            f"JOIN events e ON e.source = fts.source AND e.event_id = fts.event_id "
            f"LEFT JOIN sessions s ON s.source = e.source AND s.id = e.session_id "
            f"WHERE events_fts MATCH ?"
        )
        params: list = [safe_query]
        if session_id:
            sql += " AND fts.session_id = ?"
            params.append(session_id)
        if source:
            sql += " AND fts.source = ?"
            params.append(source)
        sql += " ORDER BY rank LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self._conn.execute(sql, params).fetchall()
        return {
            "data": [_row_to_dict(r) for r in rows],
            "meta": _pagination_meta(page, limit, total),
        }

    def rebuild_fts_index(self) -> int:
        warn = check_jieba_cjk_coverage(self._conn)
        if warn:
            logger.warning("⚠️  %s", warn)
        self._conn.execute("DROP TABLE IF EXISTS events_fts")
        self._conn.execute("DROP TRIGGER IF EXISTS events_ai")
        self._conn.executescript(FTS_SCHEMA)
        # Ensure the (legacy) FTS table carries the source column if it was
        # recreated from an older schema that lacked it.
        with contextlib.suppress(sqlite3.OperationalError):
            self._conn.execute("ALTER TABLE events_fts ADD COLUMN source UNINDEXED")

        events_has_source = _column_exists(self._conn, "events", "source")
        if events_has_source:
            select_sql = "SELECT content_text, session_id, event_id, source FROM events"
            insert_sql = (
                "INSERT INTO events_fts(content_text, session_id, event_id, source) "
                "VALUES (?, ?, ?, ?)"
            )
        else:
            # Pre-v4 DB: events table has no source column yet. Rebuild without it;
            # v4 migration backfills events_fts.source afterwards.
            select_sql = "SELECT content_text, session_id, event_id FROM events"
            insert_sql = (
                "INSERT INTO events_fts(content_text, session_id, event_id) VALUES (?, ?, ?)"
            )

        # Process in batches so a large table never has to fit entirely in memory
        # and the rebuild never holds one giant transaction open (which would stall
        # concurrent readers and risk a huge rollback on crash). Each batch is
        # tokenized + inserted + committed independently; a mid-rebuild crash loses
        # only the current batch and the next run resumes by re-dropping the table.
        total = self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        batch = 5000
        processed = 0
        for offset in range(0, total, batch):
            rows = self._conn.execute(
                f"{select_sql} ORDER BY id LIMIT ? OFFSET ?", (batch, offset)
            ).fetchall()
            if not rows:
                continue
            if events_has_source:
                values = [(_tokenize_for_fts(r[0]), r[1], r[2], r[3]) for r in rows]
            else:
                values = [(_tokenize_for_fts(r[0]), r[1], r[2]) for r in rows]
            self._conn.executemany(insert_sql, values)
            self._conn.commit()
            processed += len(rows)
        return processed

    # -- LIKE fallback --------------------------------------------

    def _search_like(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 20,
        source: str | None = None,
    ) -> list[dict]:
        pattern = f"%{query}%"
        sql = (
            f"SELECT {EVENT_COLS} FROM events e "
            f"LEFT JOIN sessions s ON s.source = e.source AND s.id = e.session_id "
            f"WHERE e.content_text LIKE ?"
        )
        params: list = [pattern]
        if session_id:
            sql += " AND e.session_id = ?"
            params.append(session_id)
        if source:
            sql += " AND e.source = ?"
            params.append(source)
        sql += " ORDER BY e.timestamp DESC LIMIT ?"
        params.append(limit)
        return [_row_to_dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def _search_like_paginated(
        self,
        query: str,
        session_id: str | None = None,
        page: int = 1,
        per_page: int = 20,
        source: str | None = None,
    ) -> dict:
        pattern = f"%{query}%"
        offset = (page - 1) * per_page

        count_sql = "SELECT COUNT(*) FROM events e WHERE e.content_text LIKE ?"
        count_params: list = [pattern]
        if session_id:
            count_sql += " AND e.session_id = ?"
            count_params.append(session_id)
        if source:
            count_sql += " AND e.source = ?"
            count_params.append(source)
        total = self._conn.execute(count_sql, count_params).fetchone()[0]

        sql = (
            f"SELECT {EVENT_COLS} FROM events e "
            f"LEFT JOIN sessions s ON s.source = e.source AND s.id = e.session_id "
            f"WHERE e.content_text LIKE ?"
        )
        params: list = [pattern]
        if session_id:
            sql += " AND e.session_id = ?"
            params.append(session_id)
        if source:
            sql += " AND e.source = ?"
            params.append(source)
        sql += " ORDER BY e.timestamp DESC LIMIT ? OFFSET ?"
        params.extend([per_page, offset])

        rows = self._conn.execute(sql, params).fetchall()
        return {
            "data": [_row_to_dict(r) for r in rows],
            "meta": _pagination_meta(page, per_page, total),
        }

    # -- memory_records full-text (BM25 half of hybrid search) -------

    def _memory_fts_enabled(self) -> bool:
        try:
            return (
                self._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_fts'"
                ).fetchone()
                is not None
            )
        except sqlite3.Error:
            return False

    def search_memory_fts(
        self, query: str, limit: int = 20, source: str | None = None
    ) -> list[dict]:
        """FTS5 BM25 search over memory_records content + topics."""
        if not self._memory_fts_enabled():
            return []
        tokenized = self._tokenized_fts_query(query)
        safe = _escape_fts5_query(tokenized)
        sql = (
            "SELECT m.id, m.type, m.content, m.topics, m.source, m.session_id, "
            "snippet(memory_fts, 0, '<mark>', '</mark>', '...', 32) as snippet, "
            "bm25(memory_fts) as rank "
            "FROM memory_fts fts "
            "JOIN memory_records m ON m.id = CAST(fts.record_id AS INTEGER) "
            "WHERE memory_fts MATCH ?"
        )
        params: list = [safe]
        if source:
            sql += " AND fts.source = ?"
            params.append(source)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        return [_row_to_dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def index_memory_record(self, rec_id: int, content: str, topics: str, source: str) -> None:
        """Insert/update one memory record into memory_fts (jieba-pre-tokenized)."""
        if not self._memory_fts_enabled():
            return
        self._conn.execute("DELETE FROM memory_fts WHERE record_id=?", (str(rec_id),))
        self._conn.execute(
            "INSERT INTO memory_fts(content, topics, record_id, source) VALUES (?, ?, ?, ?)",
            (
                _tokenize_for_fts(content or ""),
                _tokenize_for_fts(topics or ""),
                str(rec_id),
                source,
            ),
        )
        self._conn.commit()

    def reindex_memory_fts(self) -> int:
        """Rebuild memory_fts from all memory_records. Idempotent."""
        if not self._memory_fts_enabled():
            return 0
        self._conn.execute("DROP TABLE IF EXISTS memory_fts")
        self._conn.execute(
            "CREATE VIRTUAL TABLE memory_fts USING fts5("
            "content, topics, record_id UNINDEXED, source UNINDEXED, tokenize='unicode61')"
        )
        rows = self._conn.execute(
            "SELECT id, content, topics, source FROM memory_records"
        ).fetchall()
        for r in rows:
            self._conn.execute(
                "INSERT INTO memory_fts(content, topics, record_id, source) VALUES (?, ?, ?, ?)",
                (
                    _tokenize_for_fts(r["content"] or ""),
                    _tokenize_for_fts(r["topics"] or ""),
                    str(r["id"]),
                    r["source"],
                ),
            )
        self._conn.commit()
        return len(rows)


class SqliteVectorIndex:
    """Pure-Python cosine vector store backed by the ``embeddings`` table.

    Vectors are stored as float32 BLOBs (``array('f')``), normalized at write
    time so a dot product with a normalized query equals cosine similarity.
    No numpy dependency — at memory-record scale (hundreds–low-thousands) the
    overhead is sub-millisecond.
    """

    OWNER_TABLES = {"memory": "memory_records"}

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    # -- helpers --------------------------------------------------

    @staticmethod
    def _normalize(vec: list[float]) -> list[float]:
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    @staticmethod
    def _pack(vec: list[float]) -> bytes:
        return array.array("f", vec).tobytes()

    @staticmethod
    def _unpack(blob: bytes) -> list[float]:
        a = array.array("f")
        a.frombytes(blob)
        return list(a)

    @staticmethod
    def _content_hash(text: str) -> str:
        return hashlib.sha256((text or "").encode("utf-8")).hexdigest()

    # -- VectorIndex Protocol --------------------------------------

    def upsert_vectors(self, items: list[VectorItem]) -> int:
        now = datetime.now(UTC).isoformat()
        count = 0
        for it in items:
            blob = self._pack(self._normalize(it.vector))
            self._conn.execute(
                "INSERT INTO embeddings "
                "(owner_type, owner_id, model, dim, vector, content_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(owner_type, owner_id, model) DO UPDATE SET "
                "dim=excluded.dim, vector=excluded.vector, "
                "content_hash=excluded.content_hash, created_at=excluded.created_at",
                (
                    it.owner_type,
                    str(it.owner_id),
                    it.model,
                    it.dim,
                    blob,
                    it.content_hash,
                    now,
                ),
            )
            count += 1
        self._conn.commit()
        return count

    def pending_for_embedding(self, owner_type: str, model: str) -> list[dict]:
        if owner_type not in self.OWNER_TABLES:
            raise ValueError(f"unknown owner_type: {owner_type!r}")
        table = self.OWNER_TABLES[owner_type]
        rows = self._conn.execute(f"SELECT id, content, topics FROM {table}").fetchall()
        have = {
            r["owner_id"]: r["content_hash"]
            for r in self._conn.execute(
                "SELECT owner_id, content_hash FROM embeddings WHERE owner_type=? AND model=?",
                (owner_type, model),
            ).fetchall()
        }
        pending = []
        for r in rows:
            rid = str(r["id"])
            if have.get(rid) != self._content_hash(r["content"]):
                pending.append({"id": r["id"], "content": r["content"], "topics": r["topics"]})
        return pending

    def search_vectors(
        self,
        qv: list[float],
        owner_type: str,
        model: str,
        limit: int = 20,
        source: str | None = None,
    ) -> list[dict]:
        if owner_type not in self.OWNER_TABLES:
            raise ValueError(f"unknown owner_type: {owner_type!r}")
        q = self._normalize(qv)
        sql = (
            "SELECT e.owner_id, e.vector, e.dim FROM embeddings e "
            "JOIN memory_records m ON m.id = CAST(e.owner_id AS INTEGER) "
            "WHERE e.owner_type=? AND e.model=?"
        )
        params: list = [owner_type, model]
        if source:
            sql += " AND m.source=?"
            params.append(source)
        rows = self._conn.execute(sql, params).fetchall()
        scored = []
        for r in rows:
            v = self._unpack(r["vector"])
            dot = sum(a * b for a, b in zip(q, v, strict=True))
            scored.append((dot, r["owner_id"]))
        scored.sort(reverse=True)
        return [{"owner_id": oid, "score": s} for s, oid in scored[:limit]]

    def vector_stats(self) -> dict:
        rows = self._conn.execute(
            "SELECT model, COUNT(*), MAX(dim) FROM embeddings GROUP BY model"
        ).fetchall()
        by_model = {r["model"]: r["COUNT(*)"] for r in rows}
        return {
            "total": sum(by_model.values()),
            "by_model": by_model,
            "dim": max((r["MAX(dim)"] for r in rows), default=0),
        }


# ===================================================================
# Facade
# ===================================================================


class SqliteStorage:
    """SQLite-backed storage with FTS5 full-text search.

    Delegates to ``SqliteSessionRepository``, ``SqliteEventRepository``,
    and ``SqliteSearchIndex`` — each operating on a shared connection.

    Implements ``bagger.storage.base.Storage`` structurally.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._sessions: SqliteSessionRepository | None = None
        self._events: SqliteEventRepository | None = None
        self._search: SqliteSearchIndex | None = None
        self._vectors: SqliteVectorIndex | None = None
        # Serialize writes. The shared connection is opened with
        # ``check_same_thread=False`` and WAL mode keeps concurrent *reads* safe,
        # but SQLite still serializes *writes* at the file level — concurrent
        # write requests (e.g. ``POST /api/scan`` racing a watcher tick) would
        # otherwise hit "database is locked". This lock makes the boundary
        # explicit and bounded.
        self._write_lock = threading.Lock()

        # Bulk-write transaction batching (see ``bulk_write`` / ``flush``).
        # While ``_bulk_active`` is True, repo-level commits are deferred (no-op)
        # and the caller flushes every ``_bulk_every`` write units via ``flush()``.
        self._bulk_active = False
        self._bulk_every = 0
        self._bulk_count = 0

    @contextlib.contextmanager
    def _write(self) -> Generator[None, None, None]:
        """Acquire the write lock for the duration of a mutating operation."""
        with self._write_lock:
            yield

    # -- bulk transaction batching -----------------------------------

    @contextlib.contextmanager
    def bulk_write(self, commit_every: int = 50) -> Generator[None, None, None]:
        """Batch commits across many writes (e.g. a full re-scan).

        While active, repo-level ``commit()`` calls are deferred (no-op) and the
        accumulated work is flushed only every ``commit_every`` write units by
        the caller's per-unit ``flush()`` — plus one final flush on exit. This
        collapses hundreds of per-file transactions (a large import) into a
        handful, since under WAL + ``synchronous=NORMAL`` each commit still
        carries fixed overhead.

        Nested bulk contexts are ignored: the outermost controls cadence.
        """
        if self._bulk_active:
            yield
            return
        self._bulk_active = True
        self._bulk_every = max(1, commit_every)
        self._bulk_count = 0
        try:
            yield
            self._conn.commit()  # final flush of any remaining writes
        finally:
            self._bulk_active = False
            self._bulk_count = 0

    def _maybe_commit(self) -> None:
        """Commit gate for repo write methods.

        Commits immediately outside a ``bulk_write`` context (current behavior,
        preserving per-file durability for the incremental watcher). Inside bulk
        mode the caller's per-unit ``flush()`` owns the transaction, so this is a
        no-op and writes accumulate into one batched transaction.
        """
        if self._bulk_active:
            return
        self._conn.commit()

    def flush(self) -> None:
        """Commit point for the caller after each write unit (e.g. one file).

        Outside bulk mode this commits immediately. Inside bulk mode it commits
        only every ``commit_every`` units, deferring the rest; the ``bulk_write``
        context manager issues a final flush on exit so no work is left pending.
        """
        if not self._bulk_active:
            self._conn.commit()
            return
        self._bulk_count += 1
        if self._bulk_count >= self._bulk_every:
            self._conn.commit()
            self._bulk_count = 0

    # -- lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Open the SQLite database, apply schema, and wire repositories."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False + busy_timeout=5000: SQLite connections are not
        # safe to share across threads, so the API opens a *fresh* connection per
        # request (see bagger.api.dependencies.get_storage) rather than reusing
        # one. Under WAL + busy_timeout, separate connections safely allow
        # concurrent readers and a single writer on the same database file, and
        # busy_timeout retries instead of raising "database is locked". The CLI is
        # single-threaded, so this has no effect there.
        self._conn = sqlite3.connect(str(self.db_path.resolve()), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            self._conn.execute("PRAGMA journal_mode=DELETE")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        # NORMAL under WAL is the recommended safe+fast combo: fsync is skipped on
        # each write (WAL checkpoint still guarantees durability against app crashes;
        # only a power/OS crash could lose the last <1s of committed writes). This
        # roughly halves write latency, which matters because the watcher appends
        # events continuously.
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(SCHEMA)
        # Drop legacy FTS auto-insert trigger — we now insert tokenized text
        # manually so that CJK queries benefit from FTS5 indexing.
        self._conn.execute("DROP TRIGGER IF EXISTS events_ai")
        self._conn.executescript(FTS_SCHEMA)
        self._conn.commit()

        self._sessions = SqliteSessionRepository(self._conn, self._maybe_commit)
        self._events = SqliteEventRepository(self._conn, self._maybe_commit)
        self._search = SqliteSearchIndex(self._conn)
        self._vectors = SqliteVectorIndex(self._conn)

        # Migrate: old FTS data was inserted raw (not tokenized) via the
        # legacy trigger.  Rebuild once on first connect, then skip.
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            self._search.rebuild_fts_index()
            self._conn.execute("PRAGMA user_version = 1")
            self._conn.commit()
        # v2..v4 live in ``bagger.storage.migrations`` to keep this facade
        # focused on query/repo orchestration. ``apply_migrations`` is crash-safe
        # and idempotent; it only runs the steps whose ``user_version`` is unset.
        apply_migrations(self._conn, lambda: self._upsert_event_edges_for_sessions(None))

    def _upsert_event_edges_for_sessions(self, session_ids: list[str] | None = None) -> None:
        """Recompute ``event_edges`` for the given sessions (None = whole DB).

        ``depth`` is the number of edges from the session root (direct children
        = 1). A cycle guard prevents infinite loops on malformed input. Edges
        are upserted (``ON CONFLICT(event_id) DO UPDATE``) so this is safe to
        re-run on any database.

        Tolerates a pre-v4 ``events`` table that lacks the ``source`` column:
        when ``source`` is absent the edge is stamped with the default
        ``'claude'`` (the only tool that existed before multi-source support).
        This keeps the v3 migration (which backfills edges) safe to run on a
        legacy DB *before* the v4 migration adds ``source`` to ``events``.
        """
        events_has_source = _column_exists(self._conn, "events", "source")
        if events_has_source:
            base_cols = "event_id, parent_event_id, session_id, source"
        else:
            base_cols = "event_id, parent_event_id, session_id"

        if session_ids is None:
            rows = self._conn.execute(
                f"SELECT {base_cols} FROM events WHERE parent_event_id IS NOT NULL"
            ).fetchall()
        else:
            placeholders = ",".join("?" for _ in session_ids)
            rows = self._conn.execute(
                f"SELECT {base_cols} FROM events "
                f"WHERE parent_event_id IS NOT NULL AND session_id IN ({placeholders})",
                session_ids,
            ).fetchall()
        parent_of = {r["event_id"]: r["parent_event_id"] for r in rows}

        def depth(event_id: str) -> int:
            d = 0
            cur = parent_of.get(event_id)
            seen: set[str] = set()
            while cur is not None and cur not in seen:
                seen.add(cur)
                d += 1
                cur = parent_of.get(cur)
            return d

        if events_has_source:
            edges = [
                (
                    r["event_id"],
                    r["parent_event_id"],
                    r["session_id"],
                    depth(r["event_id"]),
                    r["source"],
                )
                for r in rows
            ]
        else:
            edges = [
                (
                    r["event_id"],
                    r["parent_event_id"],
                    r["session_id"],
                    depth(r["event_id"]),
                    "claude",
                )
                for r in rows
            ]
        if edges:
            self._conn.executemany(
                """INSERT INTO event_edges (event_id, parent_event_id, session_id, depth, source)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(event_id) DO UPDATE SET
                       parent_event_id=excluded.parent_event_id,
                       session_id=excluded.session_id,
                       depth=excluded.depth,
                       source=excluded.source""",
                edges,
            )

    def upsert_event_edges(self, events: list[MemoryEvent]) -> None:
        """Derive and upsert ``event_edges`` for a batch of just-inserted events.

        Called from the shared sync pipeline (``sync_file``) immediately after
        ``insert_events``, so edges stay in lock-step with events for both
        incremental watch and full re-scan. Depth is recomputed per affected
        session — cheap, since a single session is at most a few thousand events.

        This is the single write point that keeps ``event_edges`` fresh (
        "Freshness guarantee").
        """
        with self._write():
            session_ids = list({e.session_id for e in events})
            if session_ids:
                self._upsert_event_edges_for_sessions(session_ids)
                self._maybe_commit()

    def get_event_edges(self, session_id: str, source: str | None = None) -> list[dict]:
        """Return all edges for a session (child -> parent + depth)."""
        if source is not None:
            rows = self._conn.execute(
                "SELECT event_id, parent_event_id, session_id, depth "
                "FROM event_edges WHERE session_id = ? AND source = ? "
                "ORDER BY depth, event_id",
                (session_id, source),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT event_id, parent_event_id, session_id, depth "
                "FROM event_edges WHERE session_id = ? ORDER BY depth, event_id",
                (session_id,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_session_tree(self, session_id: str, source: str | None = None) -> list[dict]:
        """Return the session as a forest of nested nodes.

        Each node: ``{event_id, role, timestamp, depth, children:[...]}``. Roots
        are events whose ``parent_event_id`` is NULL (absent from ``event_edges``).
        """
        if source is not None:
            rows = self._conn.execute(
                "SELECT event_id, role, timestamp, parent_event_id "
                "FROM events WHERE session_id = ? AND source = ?",
                (session_id, source),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT event_id, role, timestamp, parent_event_id FROM events "
                "WHERE session_id = ?",
                (session_id,),
            ).fetchall()
        nodes: dict[str, dict] = {}
        for r in rows:
            nodes[r["event_id"]] = {
                "event_id": r["event_id"],
                "role": r["role"],
                "timestamp": r["timestamp"],
                "depth": 0,
                "children": [],
            }
        roots: list[dict] = []
        for r in rows:
            node = nodes[r["event_id"]]
            pid = r["parent_event_id"]
            if pid and pid in nodes:
                nodes[pid]["children"].append(node)
            else:
                roots.append(node)
        if source is not None:
            edge_rows = self._conn.execute(
                "SELECT event_id, depth FROM event_edges WHERE session_id = ? AND source = ?",
                (session_id, source),
            ).fetchall()
        else:
            edge_rows = self._conn.execute(
                "SELECT event_id, depth FROM event_edges WHERE session_id = ?",
                (session_id,),
            ).fetchall()
        for er in edge_rows:
            if er["event_id"] in nodes:
                nodes[er["event_id"]]["depth"] = er["depth"]
        return roots

    def reconcile_event_edges(self) -> dict:
        """Verify ``event_edges`` integrity (reconciliation guard).

        Returns a report: edge count must equal the number of events that have
        a parent, orphan edges (event_id missing from ``events``) and dangling
        parent references (parent_event_id missing from ``events``) must be empty.
        """
        edge_count = self._conn.execute("SELECT COUNT(*) FROM event_edges").fetchone()[0]
        children_count = self._conn.execute(
            "SELECT COUNT(*) FROM events WHERE parent_event_id IS NOT NULL"
        ).fetchone()[0]
        orphan_rows = self._conn.execute(
            "SELECT e.event_id FROM event_edges e "
            "LEFT JOIN events ev ON e.source = ev.source AND e.event_id = ev.event_id "
            "WHERE ev.event_id IS NULL"
        ).fetchall()
        orphans = [r["event_id"] for r in orphan_rows]
        dangling = self._conn.execute(
            "SELECT COUNT(*) FROM event_edges e "
            "LEFT JOIN events p ON e.source = p.source AND e.parent_event_id = p.event_id "
            "WHERE e.parent_event_id IS NOT NULL AND p.event_id IS NULL"
        ).fetchone()[0]
        return {
            "event_edges_count": edge_count,
            "children_count": children_count,
            "consistent": edge_count == children_count and not orphans and dangling == 0,
            "orphan_edges": orphans,
            "dangling_parent_count": dangling,
        }

    def close(self) -> None:
        """Close the SQLite database and null out repositories."""
        if self._conn:
            with contextlib.suppress(sqlite3.Error):
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.close()
            self._conn = None
            self._sessions = None
            self._events = None
            self._search = None

    @property
    def conn(self) -> sqlite3.Connection:
        """The underlying SQLite connection (raises if not connected)."""
        if self._conn is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        return self._conn

    # -- Session delegation -----------------------------------------

    def upsert_session(self, session: Session) -> None:
        with self._write():
            self._sessions.upsert_session(session)  # type: ignore[union-attr]

    def session_exists(self, session_id: str, source: str | None = None) -> bool:
        return self._sessions.session_exists(session_id, source)  # type: ignore[union-attr]

    def get_session(self, session_id: str, source: str | None = None) -> dict | None:
        return self._sessions.get_session(session_id, source)  # type: ignore[union-attr]

    def find_session_by_prefix(self, prefix: str, source: str | None = None) -> dict | None:
        return self._sessions.find_session_by_prefix(prefix, source)  # type: ignore[union-attr]

    def list_sessions(self, limit: int = 50) -> list[dict]:
        return self._sessions.list_sessions(limit)  # type: ignore[union-attr]

    def list_sessions_paginated(
        self,
        page: int = 1,
        per_page: int = 50,
        sort: str = "last_message_at",
        order: str = "desc",
        project: str | None = None,
        source: str | None = None,
    ) -> dict:
        return self._sessions.list_sessions_paginated(  # type: ignore[union-attr]
            page, per_page, sort, order, project, source
        )

    def get_event_count(self, session_id: str, source: str | None = None) -> int:
        return self._sessions.get_event_count(session_id, source)  # type: ignore[union-attr]

    # -- Event delegation -------------------------------------------

    def insert_event(self, event: MemoryEvent) -> None:
        with self._write():
            self._events.insert_event(event)  # type: ignore[union-attr]

    def insert_events(self, events: list[MemoryEvent]) -> int:
        with self._write():
            return self._events.insert_events(events)  # type: ignore[union-attr]

    def get_session_events(self, session_id: str, source: str | None = None) -> list[dict]:
        return self._events.get_session_events(session_id, source)  # type: ignore[union-attr]

    def get_session_events_paginated(
        self,
        session_id: str,
        page: int = 1,
        per_page: int = 50,
        source: str | None = None,
    ) -> dict:
        return self._events.get_session_events_paginated(  # type: ignore[union-attr]
            session_id, page, per_page, source
        )

    def get_stats(self) -> dict:
        return self._events.get_stats()  # type: ignore[union-attr]

    def get_daily_stats(self, days: int = 30) -> list[dict]:
        return self._events.get_daily_stats(days)  # type: ignore[union-attr]

    def get_tool_usage_stats(self, limit: int = 20) -> list[dict]:
        return self._events.get_tool_usage_stats(limit)  # type: ignore[union-attr]

    def check_integrity(self) -> list[dict]:
        return self._events.check_integrity()  # type: ignore[union-attr]

    # -- Search delegation ------------------------------------------

    def search(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 20,
        source: str | None = None,
    ) -> list[dict]:
        return self._search.search(  # type: ignore[union-attr]
            query, session_id=session_id, limit=limit, source=source
        )

    def search_paginated(
        self,
        query: str,
        session_id: str | None = None,
        page: int = 1,
        per_page: int = 20,
        source: str | None = None,
    ) -> dict:
        return self._search.search_paginated(  # type: ignore[union-attr]
            query, session_id=session_id, page=page, per_page=per_page, source=source
        )

    def search_fts(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 20,
        page: int = 1,
        source: str | None = None,
    ) -> dict:
        return self._search.search_fts(  # type: ignore[union-attr]
            query, session_id=session_id, limit=limit, page=page, source=source
        )

    def rebuild_fts_index(self) -> int:
        with self._write():
            return self._search.rebuild_fts_index()  # type: ignore[union-attr]

    def fts_enabled(self) -> bool:
        """Whether the FTS5 virtual table exists (consumed by health/doctor)."""
        return self._search._fts_enabled()  # type: ignore[union-attr]

    # -- Vector / semantic delegation ----------------------------------

    def search_memory_vectors(
        self, qv: list[float], model: str, limit: int = 20, source: str | None = None
    ) -> list[dict]:
        return self._vectors.search_vectors(  # type: ignore[union-attr]
            qv, "memory", model, limit=limit, source=source
        )

    def upsert_vectors(self, items: list[VectorItem]) -> int:
        with self._write():
            return self._vectors.upsert_vectors(items)  # type: ignore[union-attr]

    def pending_for_embedding(self, owner_type: str, model: str) -> list[dict]:
        return self._vectors.pending_for_embedding(owner_type, model)  # type: ignore[union-attr]

    def vector_stats(self) -> dict:
        return self._vectors.vector_stats()  # type: ignore[union-attr]

    def search_memory_fts(
        self, query: str, limit: int = 20, source: str | None = None
    ) -> list[dict]:
        return self._search.search_memory_fts(query, limit=limit, source=source)  # type: ignore

    def index_memory_record(self, rec_id: int, content: str, topics: str, source: str) -> None:
        with self._write():
            self._search.index_memory_record(rec_id, content, topics, source)  # type: ignore

    def reindex_memory_fts(self) -> int:
        with self._write():
            return self._search.reindex_memory_fts()  # type: ignore

    def get_memory_records(self, ids: list[int]) -> list[dict]:
        """Return memory records by id, preserving input order is not guaranteed."""
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        rows = self._conn.execute(
            f"SELECT id, type, content, topics, confidence, source, session_id, "
            f"event_id, created_at FROM memory_records WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
