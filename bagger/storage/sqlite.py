"""SQLite storage with FTS5 full-text search for bagger."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

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


class SqliteStorage:
    """SQLite-backed storage with FTS5 full-text search."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
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

    # ---- Session operations ----

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
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()

    def session_exists(self, session_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return row is not None

    def get_session(self, session_id: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT id, summary, project_path, message_count, "
            "first_message_at, last_message_at FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "summary": row[1],
            "project_path": row[2],
            "message_count": row[3],
            "first_message_at": row[4],
            "last_message_at": row[5],
        }

    def list_sessions(self, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, summary, project_path, message_count, "
            "first_message_at, last_message_at "
            "FROM sessions ORDER BY last_message_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r[0],
                "summary": r[1],
                "project_path": r[2],
                "message_count": r[3],
                "first_message_at": r[4],
                "last_message_at": r[5],
            }
            for r in rows
        ]

    # ---- Event operations ----

    def insert_event(self, event: MemoryEvent) -> None:
        content_json = json.dumps(
            [b.model_dump() for b in event.content_blocks], ensure_ascii=False
        )
        content_text = _extract_text(event)
        self.conn.execute(
            """INSERT OR IGNORE INTO events
               (event_id, session_id, parent_event_id, timestamp, role,
                content_json, content_text, token_input, token_output,
                cwd, git_branch, model)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
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
            ),
        )
        self.conn.commit()

    def insert_events(self, events: list[MemoryEvent]) -> int:
        """Batch insert events. Returns count of new events inserted."""
        count = 0
        for event in events:
            content_json = json.dumps(
                [b.model_dump() for b in event.content_blocks], ensure_ascii=False
            )
            content_text = _extract_text(event)
            try:
                self.conn.execute(
                    """INSERT OR IGNORE INTO events
                       (event_id, session_id, parent_event_id, timestamp, role,
                        content_json, content_text, token_input, token_output,
                        cwd, git_branch, model)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
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
                    ),
                )
                count += 1
            except sqlite3.IntegrityError:
                pass  # Duplicate event_id, skip
        self.conn.commit()
        return count

    def get_event_count(self, session_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM events WHERE session_id = ?", (session_id,)
        ).fetchone()
        return row[0] if row else 0

    # ---- Full-text search (FTS5) ----

    def search(
        self,
        query: str,
        session_id: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """Full-text search with FTS5 (English) or LIKE fallback (CJK).

        SQLite FTS5 unicode61 tokenizer cannot segment CJK text,
        so queries containing Chinese/Japanese/Korean characters
        fall back to LIKE. Pure ASCII/English queries use FTS5
        with BM25 ranking, snippet highlighting, and pagination.
        """
        if self._fts_enabled() and not _contains_cjk(query):
            result = self.search_fts(query, session_id=session_id, limit=limit)
            return result["data"]
        return self._search_like(query, session_id=session_id, limit=limit)

    def _fts_enabled(self) -> bool:
        """Check if the FTS5 virtual table exists and has entries."""
        try:
            row = self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='events_fts'"
            ).fetchone()
            return row is not None
        except sqlite3.Error:
            return False

    def _search_like(
        self, query: str, session_id=None, limit=20
    ) -> list[dict]:
        """Legacy LIKE-based search as fallback."""
        like_pattern = f"%{query}%"
        sql = (
            "SELECT e.id, e.event_id, e.session_id, s.summary, e.timestamp, "
            "e.role, e.content_text, e.content_json, "
            "e.token_input, e.token_output, s.project_path "
            "FROM events e "
            "LEFT JOIN sessions s ON s.id = e.session_id "
            "WHERE e.content_text LIKE ?"
        )
        params: list = [like_pattern]
        if session_id:
            sql += " AND e.session_id = ?"
            params.append(session_id)
        sql += " ORDER BY e.timestamp DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [
            {
                "db_id": r[0],
                "event_id": r[1],
                "session_id": r[2],
                "session_summary": r[3],
                "timestamp": r[4],
                "role": r[5],
                "content_text": r[6],
                "content_json": r[7],
                "token_input": r[8],
                "token_output": r[9],
                "project_path": r[10],
            }
            for r in rows
        ]

    def search_fts(
        self,
        query: str,
        session_id: Optional[str] = None,
        limit: int = 20,
        page: int = 1,
    ) -> dict:
        """FTS5 full-text search with BM25 ranking and snippet generation.

        Args:
            query: FTS5 query string (supports phrases and prefixes).
            session_id: Optional session filter.
            limit: Results per page.
            page: Page number (1-based).

        Returns:
            Dict with 'data' (list of event dicts) and 'meta' (pagination info).
        """
        # Escape special FTS5 characters and add prefix search
        safe_query = _escape_fts5_query(query)
        offset = (page - 1) * limit

        # Count total matches
        count_sql = (
            "SELECT COUNT(*) FROM events_fts "
            "WHERE events_fts MATCH ?"
        )
        count_params: list = [safe_query]
        if session_id:
            count_sql += (
                " AND session_id = ?"
            )
            count_params.append(session_id)
        total = self.conn.execute(count_sql, count_params).fetchone()[0]

        # Search with ranking and snippets
        sql = (
            "SELECT "
            "e.id, e.event_id, e.session_id, s.summary as session_summary, "
            "e.timestamp, e.role, e.content_json, e.content_text, "
            "e.token_input, e.token_output, s.project_path, "
            "snippet(events_fts, 0, '<mark>', '</mark>', '...', 32) as snippet, "
            "bm25(events_fts, 0.0, 10.0, 5.0) as rank "
            "FROM events_fts fts "
            "JOIN events e ON e.event_id = fts.event_id "
            "LEFT JOIN sessions s ON s.id = e.session_id "
            "WHERE events_fts MATCH ?"
        )
        params = [safe_query]
        if session_id:
            sql += " AND fts.session_id = ?"
            params.append(session_id)
        sql += " ORDER BY rank LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self.conn.execute(sql, params).fetchall()
        results = []
        for r in rows:
            results.append(
                {
                    "db_id": r[0],
                    "event_id": r[1],
                    "session_id": r[2],
                    "session_summary": r[3],
                    "timestamp": r[4],
                    "role": r[5],
                    "content_json": r[6],
                    "content_text": r[7],
                    "token_input": r[8],
                    "token_output": r[9],
                    "project_path": r[10],
                    "snippet": r[11],
                    "rank": r[12],
                }
            )

        return {
            "data": results,
            "meta": {
                "page": page,
                "per_page": limit,
                "total": total,
                "pages": max(1, (total + limit - 1) // limit),
            },
        }

    def rebuild_fts_index(self) -> int:
        """Rebuild the FTS5 index from all existing events.

        Drops and recreates the FTS table and repopulates from events.
        Returns the number of events indexed.
        """
        self.conn.execute("DROP TABLE IF EXISTS events_fts")
        self.conn.execute("DROP TRIGGER IF EXISTS events_ai")
        self.conn.executescript(FTS_SCHEMA)

        # Populate from existing events
        rows = self.conn.execute(
            "SELECT content_text, session_id, event_id FROM events"
        ).fetchall()
        self.conn.executemany(
            "INSERT INTO events_fts(content_text, session_id, event_id) "
            "VALUES (?, ?, ?)",
            rows,
        )
        self.conn.commit()
        return len(rows)

    # ---- Paginated queries (for API) ----

    def list_sessions_paginated(
        self, page: int = 1, per_page: int = 50, sort: str = "last_message_at",
        order: str = "desc"
    ) -> dict:
        """List sessions with pagination support.

        Args:
            page: Page number (1-based).
            per_page: Results per page.
            sort: Column to sort by (last_message_at, message_count, etc.).
            order: Sort direction ('asc' or 'desc').

        Returns:
            Dict with 'data' and 'meta' keys.
        """
        offset = (page - 1) * per_page
        allowed_sort = {"last_message_at", "message_count", "first_message_at", "id"}
        col = sort if sort in allowed_sort else "last_message_at"
        direction = "DESC" if order.lower() == "desc" else "ASC"

        total = self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]

        rows = self.conn.execute(
            f"SELECT id, summary, project_path, message_count, "
            f"first_message_at, last_message_at "
            f"FROM sessions ORDER BY {col} {direction} NULLS LAST "
            f"LIMIT ? OFFSET ?",
            (per_page, offset),
        ).fetchall()

        return {
            "data": [
                {
                    "id": r[0],
                    "summary": r[1],
                    "project_path": r[2],
                    "message_count": r[3],
                    "first_message_at": r[4],
                    "last_message_at": r[5],
                }
                for r in rows
            ],
            "meta": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": max(1, (total + per_page - 1) // per_page),
            },
        }

    def get_daily_stats(self, days: int = 30) -> list[dict]:
        """Get daily event and token counts for charting.

        Args:
            days: Number of recent days to include.

        Returns:
            List of {date, count, tokens} dicts.
        """
        rows = self.conn.execute(
            "SELECT "
            "substr(timestamp, 1, 10) as date, "
            "COUNT(*) as count, "
            "COALESCE(SUM(token_input + token_output), 0) as tokens "
            "FROM events "
            "GROUP BY date "
            "ORDER BY date DESC "
            "LIMIT ?",
            (days,),
        ).fetchall()
        return [
            {"date": r[0], "count": r[1], "tokens": r[2]}
            for r in reversed(rows)
        ]

    def get_tool_usage_stats(self, limit: int = 20) -> list[dict]:
        """Get most frequently used tools.

        Returns:
            List of {tool_name, count} dicts sorted by count desc.
        """
        rows = self.conn.execute(
            "SELECT "
            "SUBSTR(content_text, "
            "INSTR(content_text, '[tool_use:') + 10, "
            "INSTR(SUBSTR(content_text, INSTR(content_text, '[tool_use:') + 10), ']') - 1"
            ") as tool_name, "
            "COUNT(*) as count "
            "FROM events "
            "WHERE content_text LIKE '%[tool_use:%' "
            "GROUP BY tool_name "
            "ORDER BY count DESC "
            "LIMIT ?",
            (limit,),
        ).fetchall()
        return [{"tool_name": r[0], "count": r[1]} for r in rows]

    # ---- Replay ----

    def get_session_events(
        self, session_id: str, context: int = 0
    ) -> list[dict]:
        """Get all events for a session, ordered by timestamp.

        If context > 0, also include context events before/after each hit
        (used when called from search context).
        """
        rows = self.conn.execute(
            "SELECT event_id, session_id, parent_event_id, timestamp, role, "
            "content_json, content_text, token_input, token_output, "
            "cwd, git_branch, model "
            "FROM events WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        ).fetchall()
        return [
            {
                "event_id": r[0],
                "session_id": r[1],
                "parent_event_id": r[2],
                "timestamp": r[3],
                "role": r[4],
                "content_json": r[5],
                "content_text": r[6],
                "token_input": r[7],
                "token_output": r[8],
                "cwd": r[9],
                "git_branch": r[10],
                "model": r[11],
            }
            for r in rows
        ]

    # ---- Stats ----

    def get_stats(self) -> dict:
        """Return aggregate statistics."""
        total_sessions = self.conn.execute(
            "SELECT COUNT(*) FROM sessions"
        ).fetchone()[0]
        total_events = self.conn.execute(
            "SELECT COUNT(*) FROM events"
        ).fetchone()[0]
        total_tokens = self.conn.execute(
            "SELECT COALESCE(SUM(token_input + token_output), 0) FROM events"
        ).fetchone()[0]

        user_events = self.conn.execute(
            "SELECT COUNT(*) FROM events WHERE role = 'user'"
        ).fetchone()[0]
        assistant_events = self.conn.execute(
            "SELECT COUNT(*) FROM events WHERE role = 'assistant'"
        ).fetchone()[0]

        tool_use_count = self.conn.execute(
            "SELECT COUNT(*) FROM events WHERE content_text LIKE '%tool_use%'"
        ).fetchone()[0]

        return {
            "total_sessions": total_sessions,
            "total_events": total_events,
            "total_tokens": total_tokens,
            "user_events": user_events,
            "assistant_events": assistant_events,
            "tool_uses": tool_use_count,
        }

    # ---- Doctor ----

    def check_integrity(self) -> list[dict]:
        """Run integrity checks and return list of issues (empty = healthy)."""
        issues: list[dict] = []

        try:
            self.conn.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.Error as e:
            issues.append({"level": "error", "message": f"Database corrupt: {e}"})

        event_count = self.conn.execute(
            "SELECT COUNT(*) FROM events"
        ).fetchone()[0]
        if event_count == 0:
            issues.append(
                {"level": "info", "message": "No events in database"}
            )

        sessions_without_events = self.conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE message_count = 0"
        ).fetchone()[0]
        if sessions_without_events > 0:
            issues.append(
                {
                    "level": "warn",
                    "message": f"{sessions_without_events} sessions have 0 messages",
                }
            )

        return issues


def _extract_text(event: MemoryEvent) -> str:
    """Extract concatenated plain text from content blocks for FTS indexing."""
    parts: list[str] = []
    for b in event.content_blocks:
        if b.block_type in (BlockType.TEXT, BlockType.THINKING):
            if b.text:
                parts.append(b.text)
        elif b.block_type == BlockType.TOOL_USE:
            parts.append(f"[tool_use:{b.tool_name}]")
        elif b.block_type == BlockType.TOOL_RESULT:
            if b.text:
                parts.append(f"[tool_result:{b.text[:200]}]")
    return " ".join(parts)


def _contains_cjk(text: str) -> bool:
    """Check if text contains CJK (Chinese/Japanese/Korean) characters.

    Used to decide FTS5 vs LIKE search routing.
    """
    for ch in text:
        cp = ord(ch)
        if (0x4E00 <= cp <= 0x9FFF or   # CJK Unified Ideographs
            0x3400 <= cp <= 0x4DBF or   # CJK Unified Extension A
            0xF900 <= cp <= 0xFAFF or   # CJK Compatibility
            0x3040 <= cp <= 0x309F or   # Hiragana
            0x30A0 <= cp <= 0x30FF or   # Katakana
            0xAC00 <= cp <= 0xD7AF):    # Hangul
            return True
    return False


def _escape_fts5_query(query: str) -> str:
    """Escape and format a query string for FTS5 MATCH.

    Pure ASCII queries: quoted with * for prefix matching (e.g. "auth"*).
    (This function is only called for non-CJK queries.)
    """
    query = query.strip()
    if not query:
        return '""'

    query = query.replace('"', '""')

    # Split into words and quote each with prefix match
    words = query.split()
    parts = []
    for w in words:
        if len(w) >= 2:
            parts.append(f'"{w}"*')
        else:
            parts.append(f'"{w}"')

    return " ".join(parts) if parts else f'"{query}"'
