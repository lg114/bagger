"""Tests for bulk-write transaction batching (Storage.bulk_write / flush).

The point: a full re-scan over hundreds of session files must not open one
transaction per file. We prove batching by opening a *second* connection to the
same DB — it must NOT see uncommitted bulk writes (they sit in one open
transaction until the batch flushes), but must see everything once the bulk
context exits.
"""

import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from bagger.models.event import BlockType, ContentBlock, MemoryEvent, Role
from bagger.storage.sqlite import SqliteStorage


def _make_event(event_id: str, session_id: str = "sess-1") -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        session_id=session_id,
        parent_event_id=None,
        timestamp=datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC),
        role=Role.USER,
        content_blocks=[ContentBlock(block_type=BlockType.TEXT, text="hello")],
        token_input=10,
        token_output=20,
        cwd="/tmp/project",
        git_branch="main",
        model="claude-sonnet",
    )


def _count_events(db_path: Path) -> int:
    """Count events via a fresh, independent connection (sees only committed data)."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    finally:
        conn.close()


def test_bulk_write_defers_commit_until_batch():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "b.db"
        storage = SqliteStorage(db_path)
        storage.connect()

        # Inside a bulk context that never reaches commit_every, repo commits are
        # deferred — a second connection must see nothing yet.
        with storage.bulk_write(commit_every=50):
            for i in range(5):
                storage.insert_event(_make_event(f"a{i}"))
                storage.flush()  # only flushes every 50 files; never fires here
            assert _count_events(db_path) == 0

        # Context exit issues the final flush -> everything is now durable.
        assert _count_events(db_path) == 5
        storage.close()


def test_flush_outside_bulk_commits_immediately():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "b.db"
        storage = SqliteStorage(db_path)
        storage.connect()

        # Outside a bulk context (the incremental watcher path), every write
        # commits right away.
        storage.insert_event(_make_event("d0"))
        storage.flush()
        assert _count_events(db_path) == 1
        storage.close()


def test_bulk_write_final_flush_persists_beyond_context():
    """A batch that never hits commit_every still persists via the exit flush."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "b.db"
        storage = SqliteStorage(db_path)
        storage.connect()

        with storage.bulk_write(commit_every=50):
            for i in range(3):
                storage.insert_event(_make_event(f"c{i}"))
                storage.flush()
            assert _count_events(db_path) == 0  # still uncommitted mid-batch

        assert _count_events(db_path) == 3  # exit flush committed the remainder
        storage.close()
