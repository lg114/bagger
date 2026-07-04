"""Tests for SQLite storage."""

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
    """CJK queries use LIKE fallback (FTS5 unicode61 doesn't segment CJK)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = SqliteStorage(db_path)
        storage.connect()

        event = _make_event(text="修复登录 token 过期问题")
        storage.insert_event(event)

        # CJK → LIKE fallback
        results = storage.search("登录")
        assert len(results) >= 1

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
    """CJK queries use LIKE fallback (independent of FTS5 table)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = SqliteStorage(db_path)
        storage.connect()

        event = _make_event(
            event_id="e-cn-1",
            text="实现用户登录功能，包括 token 刷新和会话管理",
        )
        storage.insert_event(event)

        # CJK queries → LIKE fallback (no snippet)
        r1 = storage.search("登录")
        assert len(r1) >= 1
        assert "登录" in r1[0]["content_text"]

        r2 = storage.search("会话管理")
        assert len(r2) >= 1

        # Mixed CJK+ASCII: LIKE since CJK is present
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
