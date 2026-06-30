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

    # ---- Full-text search ----

    def search(
        self,
        query: str,
        session_id: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """Full-text search using LIKE with optional session filter."""
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
