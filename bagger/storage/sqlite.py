"""SQLite storage with FTS5 full-text search for bagger."""

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from bagger.models.event import BlockType, MemoryEvent, Session

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    summary TEXT NOT NULL DEFAULT '',
    project_path TEXT NOT NULL DEFAULT '',
    message_count INTEGER NOT NULL DEFAULT 0,
    first_message_at TEXT,
    last_message_at TEXT,
    last_synced_at TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT UNIQUE NOT NULL,
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
    model TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_session
    ON events(session_id, timestamp);
"""

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
    content_text,
    session_id UNINDEXED,
    event_id UNINDEXED,
    tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(content_text, session_id, event_id)
    VALUES (new.content_text, new.session_id, new.event_id);
END;
"""

# ── Column lists for row→dict mapping ──────────────────────

SESSION_COLS = "id, summary, project_path, message_count, first_message_at, last_message_at"

EVENT_COLS = (
    "e.id as db_id, e.event_id, e.session_id, s.summary as session_summary, "
    "e.timestamp, e.role, e.content_json, e.content_text, "
    "e.token_input, e.token_output, s.project_path"
)

EVENT_DETAIL_COLS = (
    "event_id, session_id, parent_event_id, timestamp, role, "
    "content_json, content_text, token_input, token_output, "
    "cwd, git_branch, model"
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
    """Check if text contains CJK characters (routing FTS5 vs LIKE)."""
    return bool(_CJK_RE.search(text))


def _escape_fts5_query(query: str) -> str:
    """Escape and format a query string for FTS5 MATCH.

    Pure ASCII queries: quoted with * for prefix matching (e.g. "auth"*).
    Only called for non-CJK queries.
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


# ── Row helpers ────────────────────────────────────────────


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a sqlite3.Row to a plain dict using column names."""
    return dict(row)


# ── Storage ────────────────────────────────────────────────

_INSERT_EVENT_SQL = """INSERT OR IGNORE INTO events
    (event_id, session_id, parent_event_id, timestamp, role,
     content_json, content_text, token_input, token_output,
     cwd, git_branch, model)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""


class SqliteStorage:
    """SQLite-backed storage with FTS5 full-text search."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> None:
        # Ensure parent directory exists (needed for WAL file creation)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path.resolve()))
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            # WAL can fail on some Windows configurations (restricted fs,
            # network drives, etc.). Fall back to DELETE (default) mode —
            # slightly less concurrent but fully functional.
            self._conn.execute("PRAGMA journal_mode=DELETE")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._conn.executescript(FTS_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        return self._conn

    # ── Session operations ──────────────────────────────────

    def upsert_session(self, session: Session) -> None:
        self.conn.execute(
            """INSERT INTO sessions (id, summary, project_path, message_count,
               first_message_at, last_message_at, last_synced_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
               summary=excluded.summary,
               project_path=excluded.project_path,
               message_count=excluded.message_count,
               first_message_at=excluded.first_message_at,
               last_message_at=excluded.last_message_at,
               last_synced_at=excluded.last_synced_at""",
            (
                session.session_id,
                session.summary,
                session.project_path,
                session.message_count,
                session.first_message_at.isoformat() if session.first_message_at else None,
                session.last_message_at.isoformat() if session.last_message_at else None,
                datetime.now(UTC).isoformat(),
            ),
        )
        self.conn.commit()

    def session_exists(self, session_id: str) -> bool:
        return (
            self.conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone()
            is not None
        )

    def get_session(self, session_id: str) -> dict | None:
        row = self.conn.execute(
            f"SELECT {SESSION_COLS} FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        return _row_to_dict(row) if row else None

    def find_session_by_prefix(self, prefix: str) -> dict | None:
        """Find a session by ID prefix match. Returns None if ambiguous (0 or >1)."""
        rows = self.conn.execute(
            f"SELECT {SESSION_COLS} FROM sessions WHERE id LIKE ?",
            (f"{prefix}%",),
        ).fetchall()
        if len(rows) == 1:
            return _row_to_dict(rows[0])
        return None

    def list_sessions(self, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            f"SELECT {SESSION_COLS} FROM sessions ORDER BY last_message_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    # ── Event operations ───────────────────────────────────

    def _event_params(self, event: MemoryEvent) -> tuple:
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
        )

    def insert_event(self, event: MemoryEvent) -> None:
        self.conn.execute(_INSERT_EVENT_SQL, self._event_params(event))
        self.conn.commit()

    def insert_events(self, events: list[MemoryEvent]) -> int:
        """Batch insert events. Returns count of new events inserted."""
        params = [self._event_params(e) for e in events]
        self.conn.executemany(_INSERT_EVENT_SQL, params)
        # executemany with OR IGNORE — count by comparing rows affected
        # But sqlite3 doesn't give rowcount for executemany; use change count
        before = self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        self.conn.commit()
        after = self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        return after - before

    def get_event_count(self, session_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM events WHERE session_id = ?", (session_id,)
        ).fetchone()
        return row[0] if row else 0

    # ── Full-text search ────────────────────────────────────

    def search(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """FTS5 (English) or LIKE fallback (CJK). Returns flat list for CLI."""
        if self._fts_enabled() and not _contains_cjk(query):
            return self.search_fts(query, session_id=session_id, limit=limit)["data"]
        return self._search_like(query, session_id=session_id, limit=limit)

    def search_paginated(
        self,
        query: str,
        session_id: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict:
        """FTS5/LIKE routing with pagination metadata for API."""
        if self._fts_enabled() and not _contains_cjk(query):
            return self.search_fts(query, session_id=session_id, page=page, limit=per_page)
        return self._search_like_paginated(
            query, session_id=session_id, page=page, per_page=per_page
        )

    def _fts_enabled(self) -> bool:
        """Check if the FTS5 virtual table exists."""
        try:
            return (
                self.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='events_fts'"
                ).fetchone()
                is not None
            )
        except sqlite3.Error:
            return False

    def _search_like(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """LIKE-based search fallback."""
        pattern = f"%{query}%"
        sql = (
            f"SELECT {EVENT_COLS} FROM events e "
            f"LEFT JOIN sessions s ON s.id = e.session_id "
            f"WHERE e.content_text LIKE ?"
        )
        params: list = [pattern]
        if session_id:
            sql += " AND e.session_id = ?"
            params.append(session_id)
        sql += " ORDER BY e.timestamp DESC LIMIT ?"
        params.append(limit)
        return [_row_to_dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def _search_like_paginated(
        self,
        query: str,
        session_id: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict:
        """LIKE search with pagination."""
        pattern = f"%{query}%"
        offset = (page - 1) * per_page

        # Count
        count_sql = "SELECT COUNT(*) FROM events e WHERE e.content_text LIKE ?"
        count_params: list = [pattern]
        if session_id:
            count_sql += " AND e.session_id = ?"
            count_params.append(session_id)
        total = self.conn.execute(count_sql, count_params).fetchone()[0]

        # Fetch
        sql = (
            f"SELECT {EVENT_COLS} FROM events e "
            f"LEFT JOIN sessions s ON s.id = e.session_id "
            f"WHERE e.content_text LIKE ?"
        )
        params: list = [pattern]
        if session_id:
            sql += " AND e.session_id = ?"
            params.append(session_id)
        sql += " ORDER BY e.timestamp DESC LIMIT ? OFFSET ?"
        params.extend([per_page, offset])

        rows = self.conn.execute(sql, params).fetchall()
        return {
            "data": [_row_to_dict(r) for r in rows],
            "meta": _pagination_meta(page, per_page, total),
        }

    def search_fts(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 20,
        page: int = 1,
    ) -> dict:
        """FTS5 full-text search with BM25 ranking and snippet generation."""
        safe_query = _escape_fts5_query(query)
        offset = (page - 1) * limit

        # Count
        count_sql = "SELECT COUNT(*) FROM events_fts WHERE events_fts MATCH ?"
        count_params: list = [safe_query]
        if session_id:
            count_sql += " AND session_id = ?"
            count_params.append(session_id)
        total = self.conn.execute(count_sql, count_params).fetchone()[0]

        # Search
        sql = (
            f"SELECT {EVENT_COLS}, "
            f"snippet(events_fts, 0, '<mark>', '</mark>', '...', 32) as snippet, "
            f"bm25(events_fts, 0.0, 10.0, 5.0) as rank "
            f"FROM events_fts fts "
            f"JOIN events e ON e.event_id = fts.event_id "
            f"LEFT JOIN sessions s ON s.id = e.session_id "
            f"WHERE events_fts MATCH ?"
        )
        params: list = [safe_query]
        if session_id:
            sql += " AND fts.session_id = ?"
            params.append(session_id)
        sql += " ORDER BY rank LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self.conn.execute(sql, params).fetchall()
        return {
            "data": [_row_to_dict(r) for r in rows],
            "meta": _pagination_meta(page, limit, total),
        }

    def rebuild_fts_index(self) -> int:
        """Rebuild the FTS5 index. Returns number of events indexed."""
        self.conn.execute("DROP TABLE IF EXISTS events_fts")
        self.conn.execute("DROP TRIGGER IF EXISTS events_ai")
        self.conn.executescript(FTS_SCHEMA)

        rows = self.conn.execute("SELECT content_text, session_id, event_id FROM events").fetchall()
        self.conn.executemany(
            "INSERT INTO events_fts(content_text, session_id, event_id) VALUES (?, ?, ?)",
            [tuple(r) for r in rows],
        )
        self.conn.commit()
        return len(rows)

    # ── Paginated queries ──────────────────────────────────

    def list_sessions_paginated(
        self,
        page: int = 1,
        per_page: int = 50,
        sort: str = "last_message_at",
        order: str = "desc",
    ) -> dict:
        """List sessions with pagination."""
        offset = (page - 1) * per_page
        allowed_sort = {"last_message_at", "message_count", "first_message_at", "id"}
        col = sort if sort in allowed_sort else "last_message_at"
        direction = "DESC" if order.lower() == "desc" else "ASC"

        total = self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        rows = self.conn.execute(
            f"SELECT {SESSION_COLS} FROM sessions "
            f"ORDER BY {col} {direction} NULLS LAST LIMIT ? OFFSET ?",
            (per_page, offset),
        ).fetchall()

        return {
            "data": [_row_to_dict(r) for r in rows],
            "meta": _pagination_meta(page, per_page, total),
        }

    def get_daily_stats(self, days: int = 30) -> list[dict]:
        """Get daily event and token counts for charting."""
        rows = self.conn.execute(
            "SELECT substr(timestamp, 1, 10) as date, "
            "COUNT(*) as count, "
            "COALESCE(SUM(token_input + token_output), 0) as tokens "
            "FROM events GROUP BY date ORDER BY date DESC LIMIT ?",
            (days,),
        ).fetchall()
        return [_row_to_dict(r) for r in reversed(rows)]

    def get_tool_usage_stats(self, limit: int = 20) -> list[dict]:
        """Get most frequently used tools."""
        rows = self.conn.execute(
            "SELECT "
            "SUBSTR(content_text, "
            "INSTR(content_text, '[tool_use:') + 10, "
            "INSTR(SUBSTR(content_text, INSTR(content_text, '[tool_use:') + 10), ']') - 1"
            ") as tool_name, "
            "COUNT(*) as count "
            "FROM events WHERE content_text LIKE '%[tool_use:%' "
            "GROUP BY tool_name ORDER BY count DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    # ── Replay ──────────────────────────────────────────────

    def get_session_events(self, session_id: str, context: int = 0) -> list[dict]:
        """Get all events for a session, ordered by timestamp."""
        rows = self.conn.execute(
            f"SELECT {EVENT_DETAIL_COLS} FROM events WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    # ── Stats ───────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return aggregate statistics (combined query)."""
        row = self.conn.execute(
            "SELECT "
            "COUNT(*) as total_events, "
            "COALESCE(SUM(token_input + token_output), 0) as total_tokens, "
            "SUM(CASE WHEN role='user' THEN 1 ELSE 0 END) as user_events, "
            "SUM(CASE WHEN role='assistant' THEN 1 ELSE 0 END) as assistant_events "
            "FROM events"
        ).fetchone()
        total_sessions = self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        tool_uses = self.conn.execute(
            "SELECT COUNT(*) FROM events WHERE content_text LIKE '%tool_use%'"
        ).fetchone()[0]

        return {
            "total_sessions": total_sessions,
            "total_events": row["total_events"],
            "total_tokens": row["total_tokens"],
            "user_events": row["user_events"],
            "assistant_events": row["assistant_events"],
            "tool_uses": tool_uses,
        }

    # ── Doctor ──────────────────────────────────────────────

    def check_integrity(self) -> list[dict]:
        """Run integrity checks. Empty list = healthy."""
        issues: list[dict] = []

        try:
            self.conn.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.Error as e:
            issues.append({"level": "error", "message": f"Database corrupt: {e}"})

        if self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0:
            issues.append({"level": "info", "message": "No events in database"})

        empty_sessions = self.conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE message_count = 0"
        ).fetchone()[0]
        if empty_sessions:
            issues.append(
                {"level": "warn", "message": f"{empty_sessions} sessions have 0 messages"}
            )

        return issues


def _pagination_meta(page: int, per_page: int, total: int) -> dict:
    """Build pagination metadata dict."""
    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": max(1, (total + per_page - 1) // per_page),
    }
