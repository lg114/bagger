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

Module-level helpers (``_row_to_dict``, ``_extract_text``, ``_contains_cjk``,
etc.) are shared across repos and remain stateless.
"""

import contextlib
import json
import re
import sqlite3
import threading
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

from bagger.models.event import BlockType, MemoryEvent, Session

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
    "e.id as db_id, e.event_id, e.session_id, s.summary as session_summary, "
    "e.timestamp, e.role, e.content_json, e.content_text, "
    "e.token_input, e.token_output, s.project_path"
)

EVENT_DETAIL_COLS = (
    "event_id, session_id, source, parent_event_id, timestamp, role, "
    "content_json, content_text, token_input, token_output, "
    "cwd, git_branch, model, "
    "token_cache_read, token_cache_write, cost_usd, currency, service_tier, provider"
)

# ── CJK detection ──────────────────────────────────────────

_CJK_RE = re.compile(
    r"["
    r"\u4e00-\u9fff"  # CJK Unified Ideographs
    r"\u3400-\u4dbf"  # CJK Unified Extension A
    r"\uf900-\ufaff"  # CJK Compatibility
    r"\u3040-\u309f"  # Hiragana
    r"\u30a0-\u30ff"  # Katakana
    r"\uac00-\ud7af"  # Hangul
    r"]"
)


def _contains_cjk(text: str) -> bool:
    """Check if text contains CJK characters."""
    return bool(_CJK_RE.search(text))


_jieba_cached: bool | None = None  # tri-state: None=not checked, True/False=result


def _jieba_available() -> bool:
    """True if jieba is importable (cached after first check)."""
    global _jieba_cached
    if _jieba_cached is None:
        try:
            import jieba  # noqa: F401

            _jieba_cached = True
        except ImportError:
            _jieba_cached = False
    return _jieba_cached


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

    Uses ``HMM=False`` to avoid over-segmentation (HMM sometimes splits common
    words like "会话" into single characters "会"+"话", which breaks FTS matching).

    Returns the input unchanged when jieba is unavailable or the text is pure ASCII.
    """
    if not text or not _contains_cjk(text) or not _jieba_available():
        return text
    import jieba

    return " ".join(jieba.cut(text, HMM=False))


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a sqlite3.Row to a plain dict using column names."""
    return dict(row)


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """True if ``column`` is present on ``table`` (used by migrations)."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


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

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

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
        self._conn.commit()
        # Single-point write: commit immediately so direct callers
        # (CLI, tests, one-off upserts) see their session persisted without
        # having to remember to commit. ``SyncService.sync_file`` additionally
        # commits at the end to bundle the events + edges + session into one
        # transaction for batch imports.

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

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

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
        self._conn.commit()

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
        self._conn.commit()
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
            "COALESCE(SUM(token_input), 0) as total_input "
            "FROM events"
        ).fetchone()
        total_sessions = self._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        tool_uses = self._conn.execute("SELECT COUNT(*) FROM tool_uses").fetchone()[0]

        cache_denom = row["cache_read"] + row["total_input"]
        cache_hit_rate = row["cache_read"] / cache_denom if cache_denom > 0 else None

        per_model = self._conn.execute(
            "SELECT model, "
            "COALESCE(SUM(token_input + token_output), 0) as tokens, "
            "COUNT(*) as events "
            "FROM events WHERE model IS NOT NULL "
            "GROUP BY model ORDER BY tokens DESC LIMIT 10"
        ).fetchall()
        per_provider = self._conn.execute(
            "SELECT provider, "
            "COALESCE(SUM(token_input + token_output), 0) as tokens, "
            "COUNT(*) as events "
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
            "per_model": [_row_to_dict(r) for r in per_model],
            "per_provider": [_row_to_dict(r) for r in per_provider],
            "per_source": [_row_to_dict(r) for r in per_source],
        }

    def get_daily_stats(self, days: int = 30) -> list[dict]:
        rows = self._conn.execute(
            "SELECT substr(timestamp, 1, 10) as date, "
            "COUNT(*) as count, "
            "COALESCE(SUM(token_input + token_output), 0) as tokens "
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
        if not _contains_cjk(query) or not _jieba_available():
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
        self._conn.execute("DROP TABLE IF EXISTS events_fts")
        self._conn.execute("DROP TRIGGER IF EXISTS events_ai")
        self._conn.executescript(FTS_SCHEMA)
        # Ensure the (legacy) FTS table carries the source column if it was
        # recreated from an older schema that lacked it.
        with contextlib.suppress(sqlite3.OperationalError):
            self._conn.execute("ALTER TABLE events_fts ADD COLUMN source UNINDEXED")

        events_has_source = _column_exists(self._conn, "events", "source")
        if events_has_source:
            rows = self._conn.execute(
                "SELECT content_text, session_id, event_id, source FROM events"
            ).fetchall()
            sql = (
                "INSERT INTO events_fts(content_text, session_id, event_id, source) "
                "VALUES (?, ?, ?, ?)"
            )
            values = [(_tokenize_for_fts(r[0]), r[1], r[2], r[3]) for r in rows]
        else:
            # Pre-v4 DB: events table has no source column yet. Rebuild without it;
            # v4 migration backfills events_fts.source afterwards.
            rows = self._conn.execute(
                "SELECT content_text, session_id, event_id FROM events"
            ).fetchall()
            sql = "INSERT INTO events_fts(content_text, session_id, event_id) VALUES (?, ?, ?)"
            values = [(_tokenize_for_fts(r[0]), r[1], r[2]) for r in rows]

        self._conn.executemany(sql, values)
        self._conn.commit()
        return len(rows)

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
        # Serialize writes. The shared connection is opened with
        # ``check_same_thread=False`` and WAL mode keeps concurrent *reads* safe,
        # but SQLite still serializes *writes* at the file level — concurrent
        # write requests (e.g. ``POST /api/scan`` racing a watcher tick) would
        # otherwise hit "database is locked". This lock makes the boundary
        # explicit and bounded.
        self._write_lock = threading.Lock()

    @contextlib.contextmanager
    def _write(self) -> Generator[None, None, None]:
        """Acquire the write lock for the duration of a mutating operation."""
        with self._write_lock:
            yield

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
        self._conn.executescript(SCHEMA)
        # Drop legacy FTS auto-insert trigger — we now insert tokenized text
        # manually so that CJK queries benefit from FTS5 indexing.
        self._conn.execute("DROP TRIGGER IF EXISTS events_ai")
        self._conn.executescript(FTS_SCHEMA)
        self._conn.commit()

        self._sessions = SqliteSessionRepository(self._conn)
        self._events = SqliteEventRepository(self._conn)
        self._search = SqliteSearchIndex(self._conn)

        # Migrate: old FTS data was inserted raw (not tokenized) via the
        # legacy trigger.  Rebuild once on first connect, then skip.
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            self._search.rebuild_fts_index()
            self._conn.execute("PRAGMA user_version = 1")
            self._conn.commit()
        if version < 2:
            self._apply_migration_v2()
            self._conn.execute("PRAGMA user_version = 2")
            self._conn.commit()
        if version < 3:
            self._apply_migration_v3()
            self._conn.execute("PRAGMA user_version = 3")
            self._conn.commit()
        if version < 4:
            self._apply_migration_v4()

    def _apply_migration_v2(self) -> None:
        """Add usage/provider columns to legacy (v1) databases.

        New databases get these columns from SCHEMA directly; this only
        patches databases created before this migration existed.
        """
        alters = [
            "ALTER TABLE events ADD COLUMN token_cache_read INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE events ADD COLUMN token_cache_write INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE events ADD COLUMN cost_usd REAL",
            "ALTER TABLE events ADD COLUMN currency TEXT NOT NULL DEFAULT 'USD'",
            "ALTER TABLE events ADD COLUMN service_tier TEXT",
            "ALTER TABLE events ADD COLUMN provider TEXT",
        ]
        for sql in alters:
            with contextlib.suppress(sqlite3.OperationalError):
                self._conn.execute(sql)  # column already exists
        self._conn.commit()

    def _apply_migration_v3(self) -> None:
        """Add event-edge topology + session lineage columns.

        Idempotent and safe to re-run on any database that already has
        ``events``/``sessions``. The ``event_edges`` table is *derived* from
        ``events.parent_event_id``; this backfills it for existing data so a
        legacy DB is not left with an empty tree.
        """
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS event_edges (
                event_id TEXT PRIMARY KEY,
                parent_event_id TEXT,
                session_id TEXT NOT NULL,
                depth INTEGER NOT NULL DEFAULT 0,
                source TEXT,
                UNIQUE(event_id)
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_event_edges_session ON event_edges(session_id)"
        )

        alters = [
            "ALTER TABLE sessions ADD COLUMN parent_session_id TEXT",
            "ALTER TABLE sessions ADD COLUMN resume_of TEXT",
            "ALTER TABLE sessions ADD COLUMN is_compaction INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE sessions ADD COLUMN compaction_of TEXT",
        ]
        for sql in alters:
            with contextlib.suppress(sqlite3.OperationalError):
                self._conn.execute(sql)  # column already exists

        self._backfill_event_edges()
        self._conn.commit()

    def _column_exists(self, table: str, column: str) -> bool:
        """True if ``column`` is present on ``table`` (used by migrations)."""
        rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r["name"] == column for r in rows)

    def _apply_migration_v4(self) -> None:
        """Introduce multi-source identity (design doc (a)).

        Rebuilds ``sessions`` (composite PK ``(source, id)``) and ``events``
        (composite UNIQUE ``(source, event_id)``) — SQLite cannot ALTER a
        PRIMARY KEY or DROP a UNIQUE constraint, so both tables are recreated.
        Legacy rows are backfilled with ``source='claude'``. ``event_edges`` /
        ``events_fts`` gain a ``source`` column (default 'claude') so joins and
        per-source filtering are correct.

        Crash-safe: all steps run inside one implicit transaction and
        ``user_version`` is set to 4 within the same commit, so a mid-migration
        crash rolls back and a re-run starts clean. ``PRAGMA foreign_keys=OFF``
        is issued *before* any DML (it is a no-op inside a transaction) so the
        ``DROP`` of ``events`` (referenced by ``tool_uses.event_id``) is
        allowed; it is re-enabled in ``finally``.

        Idempotent: a fresh (already-v4-shaped) database already carries the
        ``source`` column, so the table rebuilds are skipped and the migration
        only backfills the derived columns — safe to run on every connect().
        """
        c = self._conn
        c.execute("PRAGMA foreign_keys=OFF")  # must precede any DML; allows DROP of `events`
        try:
            # 1) sessions — rebuild with composite PK (cannot ALTER a PRIMARY KEY).
            #    Skip when the column already exists (fresh v4 DB).
            if not _column_exists(c, "sessions", "source"):
                c.execute("DROP TABLE IF EXISTS sessions_new")
                c.execute(
                    """
                    CREATE TABLE sessions_new (
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
                    )
                    """
                )
                # SELECT 'claude', * mirrors sessions_new's (source, id, ...) order
                # automatically — adding a column to SCHEMA later won't silently drop it.
                c.execute("INSERT INTO sessions_new SELECT 'claude', * FROM sessions")
                c.execute("DROP TABLE sessions")
                c.execute("ALTER TABLE sessions_new RENAME TO sessions")

            # 2) events — rebuild with composite UNIQUE(source, event_id).
            #    (ON CONFLICT(event_id) alone would let a 2nd tool's event silently
            #    overwrite the 1st tool's row -> cross-source corruption)
            if not _column_exists(c, "events", "source"):
                c.execute("DROP TABLE IF EXISTS events_new")
                c.execute(
                    """
                    CREATE TABLE events_new (
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
                    )
                    """
                )
                # old events has no `source` column, so SELECT *, 'claude' appends it last.
                c.execute("INSERT INTO events_new SELECT *, 'claude' FROM events")
                c.execute("DROP TABLE events")
                c.execute("ALTER TABLE events_new RENAME TO events")

            # Source now exists on events (rebuilt above, or already present on a
            # fresh DB) — safe to (re)create the composite index for either path.
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_source_session "
                "ON events(source, session_id, timestamp)"
            )

            # 3) event_edges — add source, backfill from sessions, reindex.
            with contextlib.suppress(sqlite3.OperationalError):
                c.execute("ALTER TABLE event_edges ADD COLUMN source TEXT")
            c.execute(
                "UPDATE event_edges SET source = COALESCE("
                "(SELECT s.source FROM sessions s WHERE s.id = event_edges.session_id), 'claude') "
                "WHERE source IS NULL"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_event_edges_source_session "
                "ON event_edges(source, session_id)"
            )

            # 4) events_fts — FTS5 *virtual* tables cannot be ALTERed at all
            #    (``virtual tables may not be altered``), so a plain
            #    ``ADD COLUMN source`` would silently no-op under ``suppress``
            #    and leave the table without ``source``. Rebuild it with the new
            #    column and backfill ``source`` from sessions instead. Skipped on
            #    fresh DBs where FTS_SCHEMA already includes ``source``.
            if not _column_exists(c, "events_fts", "source"):
                c.execute("DROP TABLE IF EXISTS events_fts_new")
                c.execute(
                    """
                    CREATE VIRTUAL TABLE events_fts_new USING fts5(
                        content_text,
                        session_id UNINDEXED,
                        event_id UNINDEXED,
                        source UNINDEXED,
                        tokenize='unicode61'
                    )
                    """
                )
                c.execute(
                    "INSERT INTO events_fts_new(rowid, content_text, session_id, event_id, source) "
                    "SELECT f.rowid, f.content_text, f.session_id, f.event_id, "
                    "COALESCE((SELECT s.source FROM sessions s WHERE s.id = f.session_id), "
                    "'claude') "
                    "FROM events_fts f"
                )
                c.execute("DROP TABLE events_fts")
                c.execute("ALTER TABLE events_fts_new RENAME TO events_fts")

            # 5) tool_uses — the FK ``event_id -> events(event_id)`` is invalid once
            #    events.event_id is no longer a single-column unique key (it is now
            #    part of UNIQUE(source, event_id)). Rebuild tool_uses to carry
            #    ``source`` and reference the composite key. Skip on fresh DBs.
            if not _column_exists(c, "tool_uses", "source"):
                c.execute("DROP TABLE IF EXISTS tool_uses_new")
                c.execute(
                    """
                    CREATE TABLE tool_uses_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        tool_id TEXT NOT NULL DEFAULT '',
                        tool_input_json TEXT NOT NULL DEFAULT '{}',
                        source TEXT NOT NULL DEFAULT 'claude',
                        FOREIGN KEY (source, event_id) REFERENCES events(source, event_id)
                    )
                    """
                )
                c.execute(
                    "INSERT INTO tool_uses_new "
                    "(id, event_id, tool_name, tool_id, tool_input_json, source) "
                    "SELECT t.id, t.event_id, t.tool_name, t.tool_id, t.tool_input_json, "
                    "COALESCE((SELECT e.source FROM events e WHERE e.event_id = t.event_id), "
                    "'claude') FROM tool_uses t"
                )
                c.execute("DROP TABLE tool_uses")
                c.execute("ALTER TABLE tool_uses_new RENAME TO tool_uses")
                c.execute("CREATE INDEX IF NOT EXISTS idx_tool_uses_event ON tool_uses(event_id)")
                c.execute("CREATE INDEX IF NOT EXISTS idx_tool_uses_name ON tool_uses(tool_name)")

            c.execute("PRAGMA user_version = 4")
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.execute("PRAGMA foreign_keys=ON")

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

    def _backfill_event_edges(self) -> None:
        """Recompute all ``event_edges`` (v3 migration + full re-scan)."""
        self._upsert_event_edges_for_sessions(None)

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
                self._conn.commit()

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
