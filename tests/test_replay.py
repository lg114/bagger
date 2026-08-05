"""Tests for terminal replay (bagger.services.replay)."""

import tempfile
from datetime import UTC, datetime
from pathlib import Path

from bagger.models.event import (
    BlockType,
    ContentBlock,
    MemoryEvent,
    Role,
)
from bagger.services.replay import replay_session
from bagger.storage.sqlite import SqliteStorage


def _make_event(
    session_id: str = "sess-replay",
    event_id: str = "evt-replay",
    role: Role = Role.USER,
    text: str = "Hello world",
    token_input: int = 10,
    token_output: int = 20,
) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        session_id=session_id,
        timestamp=datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC),
        role=role,
        content_blocks=[ContentBlock(block_type=BlockType.TEXT, text=text)],
        token_input=token_input,
        token_output=token_output,
        cwd="/tmp/project",
        git_branch="main",
        model="claude-sonnet",
    )


def test_replay_renders_valid_event():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        storage = SqliteStorage(Path(tmpdir) / "test.db")
        storage.connect()
        storage.insert_event(_make_event())

        out = replay_session(storage, "sess-replay")

        assert isinstance(out, str)
        assert "Hello world" in out
        # Token line is rendered from the event's token counters.
        assert "in=10 out=20" in out
        storage.close()


def test_replay_survives_malformed_content_json():
    """Regression guard for the P0-2 fix: a corrupted ``content_json`` must not
    crash the whole replay — it should skip that event's blocks and continue."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        storage = SqliteStorage(Path(tmpdir) / "test.db")
        storage.connect()
        storage.insert_event(_make_event(event_id="evt-good", text="good content"))
        storage.insert_event(
            _make_event(event_id="evt-bad", role=Role.ASSISTANT, text="unreachable")
        )

        # Corrupt the second event's content_json (as a migration artifact or a
        # manual edit could produce) so json.loads would raise.
        storage.conn.execute(
            "UPDATE events SET content_json = ? WHERE event_id = ?",
            ("{not valid json", "evt-bad"),
        )
        storage.conn.commit()

        # Must not raise — the malformed event is skipped, the rest renders.
        out = replay_session(storage, "sess-replay")

        assert isinstance(out, str)
        assert "good content" in out
        storage.close()


def test_replay_unknown_session_returns_message():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        storage = SqliteStorage(Path(tmpdir) / "test.db")
        storage.connect()
        out = replay_session(storage, "does-not-exist")
        assert "No events found" in out
        storage.close()
