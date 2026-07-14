"""Tests for SQLite storage."""

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from bagger.models.event import (
    BlockType,
    ContentBlock,
    MemoryEvent,
    Role,
    Session,
)
from bagger.storage.sqlite import SqliteStorage


def _make_event(
    event_id="evt-001",
    session_id="sess-1",
    role=Role.USER,
    text="Hello world",
    parent_event_id=None,
) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        session_id=session_id,
        parent_event_id=parent_event_id,
        timestamp=datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC),
        role=role,
        content_blocks=[ContentBlock(block_type=BlockType.TEXT, text=text)],
        token_input=10,
        token_output=20,
        cwd="/tmp/project",
        git_branch="main",
        model="claude-sonnet",
    )


def test_insert_and_search():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = SqliteStorage(db_path)
        storage.connect()

        event = _make_event()
        storage.insert_event(event)

        # Search
        results = storage.search("Hello")
        assert len(results) >= 1
        assert "Hello" in results[0]["content_text"]

        storage.close()


def test_insert_ignore_duplicates():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = SqliteStorage(db_path)
        storage.connect()

        event = _make_event()
        storage.insert_event(event)
        storage.insert_event(event)  # Duplicate

        assert storage.get_event_count("sess-1") == 1
        storage.close()


def test_session_upsert():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = SqliteStorage(db_path)
        storage.connect()

        session = Session(
            session_id="sess-1",
            summary="Test session",
            project_path="/tmp/project",
            message_count=3,
            first_message_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
            last_message_at=datetime(2026, 6, 30, 12, 1, tzinfo=UTC),
        )
        storage.upsert_session(session)

        sess = storage.get_session("sess-1")
        assert sess is not None
        assert sess["summary"] == "Test session"
        assert sess["message_count"] == 3

        storage.close()


def test_stats():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = SqliteStorage(db_path)
        storage.connect()

        e1 = _make_event(event_id="e1", session_id="s1", role=Role.USER)
        e2 = _make_event(event_id="e2", session_id="s1", role=Role.ASSISTANT)
        storage.insert_events([e1, e2])

        stats = storage.get_stats()
        assert stats["total_events"] == 2
        assert stats["user_events"] == 1
        assert stats["assistant_events"] == 1

        storage.close()


def test_search_chinese():
    """CJK queries use FTS5 via jieba pre-tokenization (no LIKE fallback needed)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = SqliteStorage(db_path)
        storage.connect()

        event = _make_event(text="修复登录 token 过期问题")
        storage.insert_event(event)

        # CJK → FTS5 with jieba pre-tokenization (snippets present)
        results = storage.search("登录")
        assert len(results) >= 1
        assert "snippet" in results[0]  # FTS5 snippet for CJK

        # ASCII → FTS5 (snippet present)
        results2 = storage.search("token")
        assert len(results2) >= 1
        assert "snippet" in results2[0]

        storage.close()


# ---- FTS5 specific tests ----


def test_fts_search_returns_snippets():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = SqliteStorage(db_path)
        storage.connect()

        event = _make_event(
            event_id="e-fts-1",
            text="Fix the authentication token refresh bug in the login flow",
        )
        storage.insert_event(event)

        result = storage.search_fts("authentication")
        assert len(result["data"]) >= 1
        r = result["data"][0]
        assert "authentication" in r["snippet"]
        assert r["rank"] is not None

        storage.close()


def test_fts_search_falls_back_to_like():
    """search() auto-detects FTS and uses it; falls back to LIKE otherwise."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = SqliteStorage(db_path)
        storage.connect()

        event = _make_event(
            event_id="e-fb-1",
            text="Hello FTS5 world",
        )
        storage.insert_event(event)

        # search() should use FTS5 since the table was created
        results = storage.search("FTS5")
        assert len(results) >= 1
        # Should have snippet (FTS5 path)
        assert "snippet" in results[0]
        assert "FTS5" in results[0]["snippet"]

        storage.close()


def test_search_fts_pagination():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = SqliteStorage(db_path)
        storage.connect()

        for i in range(5):
            event = _make_event(
                event_id=f"e-page-{i}",
                session_id="s-page",
                text=f"Pagination test message number {i}",
            )
            storage.insert_event(event)

        # Page 1: 3 items
        r1 = storage.search_fts("Pagination", page=1, limit=3)
        assert len(r1["data"]) == 3
        assert r1["meta"]["total"] == 5
        assert r1["meta"]["pages"] == 2

        # Page 2: 2 items
        r2 = storage.search_fts("Pagination", page=2, limit=3)
        assert len(r2["data"]) == 2

        storage.close()


def test_rebuild_fts_index():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = SqliteStorage(db_path)
        storage.connect()

        # Insert events
        events = [
            _make_event(event_id="e-rb-1", session_id="s-rb", text="First rebuild test"),
            _make_event(event_id="e-rb-2", session_id="s-rb", text="Second rebuild test"),
        ]
        storage.insert_events(events)

        # Rebuild
        count = storage.rebuild_fts_index()
        assert count == 2

        # Verify searchable after rebuild
        result = storage.search_fts("rebuild")
        assert len(result["data"]) == 2

        storage.close()


def test_fts_search_with_session_filter():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = SqliteStorage(db_path)
        storage.connect()

        e1 = _make_event(event_id="e-sf-1", session_id="s-alpha", text="Alpha session secret")
        e2 = _make_event(event_id="e-sf-2", session_id="s-beta", text="Beta session secret")
        storage.insert_events([e1, e2])

        # Global search finds both
        r_all = storage.search_fts("secret")
        assert r_all["meta"]["total"] == 2

        # Filtered search finds only one
        r_filtered = storage.search_fts("secret", session_id="s-alpha")
        assert r_filtered["meta"]["total"] == 1
        assert r_filtered["data"][0]["session_id"] == "s-alpha"

        storage.close()


def test_fts_chinese_search():
    """CJK queries use FTS5 with jieba pre-tokenization (BM25 + snippets)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = SqliteStorage(db_path)
        storage.connect()

        event = _make_event(
            event_id="e-cn-1",
            text="实现用户登录功能，包括 token 刷新和会话管理",
        )
        storage.insert_event(event)

        # CJK → FTS5 (snippets and rank present)
        r1 = storage.search("登录")
        assert len(r1) >= 1
        assert "snippet" in r1[0]
        assert "登录" in r1[0]["content_text"]

        r2 = storage.search("会话管理")
        assert len(r2) >= 1

        # Mixed CJK+ASCII → FTS5
        r3 = storage.search("token 刷新")
        assert len(r3) >= 1

        storage.close()


def test_fts_ascii_search():
    """Pure ASCII queries use FTS5 with BM25 ranking and snippets."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = SqliteStorage(db_path)
        storage.connect()

        event = _make_event(
            event_id="e-ascii-1",
            text="Fix the authentication bug in the login flow",
        )
        storage.insert_event(event)

        # search() uses FTS5 for ASCII
        results = storage.search("authentication")
        assert len(results) >= 1
        # FTS5 results have snippet field
        assert "snippet" in results[0]
        assert "authentication" in results[0]["snippet"]

        storage.close()


# ── tool_uses table ─────────────────────────────────────────


def _make_tool_event(
    event_id: str,
    tool_name: str,
    tool_id: str = "",
    tool_input: dict | None = None,
) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        session_id="sess-tools",
        timestamp=datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC),
        role=Role.ASSISTANT,
        content_blocks=[
            ContentBlock(
                block_type=BlockType.TOOL_USE,
                tool_name=tool_name,
                tool_id=tool_id,
                tool_input=tool_input,
            ),
        ],
        model="claude-sonnet",
    )


def test_tool_uses_inserted_on_event_write():
    """Inserting an event with TOOL_USE blocks writes to tool_uses table."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = SqliteStorage(db_path)
        storage.connect()

        event = _make_tool_event("evt-tool-1", "Read", tool_id="toolu_01")
        storage.insert_event(event)

        rows = storage.conn.execute(
            "SELECT event_id, tool_name, tool_id, tool_input_json FROM tool_uses"
        ).fetchall()
        assert len(rows) == 1
        row = dict(rows[0])
        assert row["event_id"] == "evt-tool-1"
        assert row["tool_name"] == "Read"
        assert row["tool_id"] == "toolu_01"
        assert json.loads(row["tool_input_json"]) == {}

        storage.close()


def test_get_tool_usage_stats_aggregates():
    """get_tool_usage_stats() correctly aggregates from tool_uses table."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = SqliteStorage(db_path)
        storage.connect()

        # Insert 3 Read, 2 Write, 1 Bash
        for i, name in enumerate(["Read", "Read", "Write", "Read", "Write", "Bash"]):
            storage.insert_event(_make_tool_event(f"evt-agg-{i}", name))
        storage.conn.commit()

        stats = storage.get_tool_usage_stats()
        assert len(stats) == 3
        assert stats[0] == {"tool_name": "Read", "count": 3}
        assert stats[1] == {"tool_name": "Write", "count": 2}
        assert stats[2] == {"tool_name": "Bash", "count": 1}

        # Limit works
        stats_limited = storage.get_tool_usage_stats(limit=2)
        assert len(stats_limited) == 2

        storage.close()


def test_tool_uses_no_tool_events():
    """Events with no TOOL_USE blocks leave tool_uses table empty."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = SqliteStorage(db_path)
        storage.connect()

        # Insert plain text event (no tool_use)
        storage.insert_event(_make_event(event_id="evt-plain"))
        storage.conn.commit()

        count = storage.conn.execute("SELECT COUNT(*) FROM tool_uses").fetchone()[0]
        assert count == 0

        storage.close()


def test_tool_uses_idempotent():
    """Re-inserting the same event does not duplicate tool_uses rows (OR IGNORE)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = SqliteStorage(db_path)
        storage.connect()

        event = _make_tool_event("evt-dup", "Write")
        storage.insert_event(event)
        storage.insert_event(event)  # same event_id
        storage.conn.commit()

        count = storage.conn.execute(
            "SELECT COUNT(*) FROM tool_uses WHERE event_id = ?",
            ("evt-dup",),
        ).fetchone()[0]
        assert count == 1

        storage.close()


def test_get_stats_tool_uses_count():
    """get_stats() tool_uses field counts from tool_uses table."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = SqliteStorage(db_path)
        storage.connect()

        for i, name in enumerate(["Read", "Write", "Read", "Bash"]):
            storage.insert_event(_make_tool_event(f"evt-stat-{i}", name))
        storage.conn.commit()

        stats = storage.get_stats()
        assert stats["tool_uses"] == 4

        storage.close()


def test_get_stats_includes_cache_rate_and_breakdown():
    """get_stats() exposes cache_hit_rate, per_model, and per_provider."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = SqliteStorage(db_path)
        storage.connect()

        e1 = _make_event(event_id="e1", session_id="s1", role=Role.USER)
        e1.token_input = 20
        e1.token_output = 10
        e1.token_cache_read = 80
        e1.model = "claude-sonnet-4"
        e1.provider = "anthropic"

        e2 = _make_event(event_id="e2", session_id="s2", role=Role.ASSISTANT)
        e2.token_input = 10
        e2.token_output = 5
        e2.token_cache_read = 40
        e2.model = "claude-sonnet-4"
        e2.provider = "anthropic"

        storage.insert_events([e1, e2])

        stats = storage.get_stats()
        # cache_hit_rate = cache_read / (cache_read + input) = 120 / 150
        assert stats["cache_hit_rate"] == 0.8
        assert stats["total_tokens"] == 45
        assert len(stats["per_model"]) == 1
        assert stats["per_model"][0]["model"] == "claude-sonnet-4"
        assert stats["per_model"][0]["tokens"] == 45
        assert len(stats["per_provider"]) == 1
        assert stats["per_provider"][0]["provider"] == "anthropic"

        storage.close()


def test_get_stats_cache_rate_none_when_no_token_data():
    """cache_hit_rate is None only when there is no token data at all."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = SqliteStorage(db_path)
        storage.connect()

        e = _make_event(event_id="e-zero")
        e.token_input = 0
        e.token_output = 0
        e.token_cache_read = 0
        storage.insert_event(e)

        stats = storage.get_stats()
        assert stats["cache_hit_rate"] is None

        storage.close()


def test_get_stats_cache_rate_zero_when_no_cache_hit():
    """With input tokens but no cache hit, rate is 0.0 (not None)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = SqliteStorage(db_path)
        storage.connect()

        # default _make_event has token_input=10 -> rate = 0 / 10 = 0.0
        storage.insert_event(_make_event(event_id="e-no-cache"))

        stats = storage.get_stats()
        assert stats["cache_hit_rate"] == 0.0

        storage.close()


def test_migration_v2_adds_usage_columns():
    """A legacy (v1) database gets the new columns via ALTER on connect()."""
    import sqlite3

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "legacy.db"
        # Simulate a pre-v2 database (events table without new columns)
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY, summary TEXT NOT NULL DEFAULT '',
                project_path TEXT NOT NULL DEFAULT '', message_count INTEGER NOT NULL DEFAULT 0,
                first_message_at TEXT, last_message_at TEXT, last_synced_at TEXT);
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL,
                session_id TEXT NOT NULL, parent_event_id TEXT, timestamp TEXT NOT NULL,
                role TEXT NOT NULL, content_json TEXT NOT NULL, content_text TEXT NOT NULL DEFAULT '',
                token_input INTEGER NOT NULL DEFAULT 0, token_output INTEGER NOT NULL DEFAULT 0,
                cwd TEXT, git_branch TEXT, model TEXT);
            CREATE TABLE tool_uses (
                id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL,
                tool_name TEXT NOT NULL, tool_id TEXT NOT NULL DEFAULT '',
                tool_input_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (event_id) REFERENCES events(event_id));
            """
        )
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
        conn.close()

        storage = SqliteStorage(db_path)
        storage.connect()  # should apply v2 migration without error

        # New columns exist and accept values after migration
        event = _make_event(event_id="migrated-1")
        event.token_cache_read = 5
        event.provider = "anthropic"
        storage.insert_event(event)

        row = storage.conn.execute(
            "SELECT token_cache_read, token_cache_write, cost_usd, currency, "
            "service_tier, provider FROM events WHERE event_id='migrated-1'"
        ).fetchone()
        d = dict(row)
        assert d["token_cache_read"] == 5
        assert d["token_cache_write"] == 0
        assert d["cost_usd"] is None
        assert d["currency"] == "USD"
        assert d["provider"] == "anthropic"

        storage.close()
