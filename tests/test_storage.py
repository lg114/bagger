"""Tests for SQLite storage."""

import tempfile
from datetime import datetime, timezone
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
        timestamp=datetime(2026, 6, 30, 12, 0, 0, tzinfo=timezone.utc),
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
            first_message_at=datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc),
            last_message_at=datetime(2026, 6, 30, 12, 1, tzinfo=timezone.utc),
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
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = SqliteStorage(db_path)
        storage.connect()

        event = _make_event(text="修复登录 token 过期问题")
        storage.insert_event(event)

        results = storage.search("登录")
        assert len(results) >= 1

        results2 = storage.search("token")
        assert len(results2) >= 1

        storage.close()
