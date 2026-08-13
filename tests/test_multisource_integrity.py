"""Regression tests for multi-source data integrity (P1 review items).

Covers three bugs where two AI tools sharing an id/event_id collided:

* P1-1: ``event_edges`` was keyed on the bare ``event_id``; the v7 migration
  rebuilds it with a composite ``(source, event_id)`` PK so one tool's edges
  no longer overwrite another's.
* P1-2: the session detail / events / tree endpoints ignored ``source``, so a
  shared session id returned mixed or ambiguous data across tools. They now
  accept ``?source=`` and scope to it (the storage layer already supported it).
* P1-3: ``upsert_session`` overwrote ``first_message_at`` on every incremental
  sync, so a session's true start time drifted to the latest batch. It now
  keeps MIN(first) / MAX(last).
"""

import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from bagger.api.app import create_app
from bagger.config import Settings
from bagger.models.event import BlockType, ContentBlock, MemoryEvent, Role, Session
from bagger.storage.sqlite import SqliteStorage


def _make_event(
    event_id: str,
    session_id: str,
    role=Role.USER,
    parent_event_id=None,
    source: str = "claude",
    ts=None,
) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        session_id=session_id,
        parent_event_id=parent_event_id,
        timestamp=ts or datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC),
        role=role,
        content_blocks=[ContentBlock(block_type=BlockType.TEXT, text="x")],
        token_input=10,
        token_output=20,
        source=source,
    )


def _override_db(tmpdir: Path) -> SqliteStorage:
    """Spin up a temporary DB and point bagger.config.settings at it."""
    import bagger.config as config

    config.settings = Settings(bagger_dir=tmpdir)
    db_path = config.settings.db_path
    storage = SqliteStorage(db_path)
    storage.connect()
    return storage


def test_event_edges_multisource_same_event_id_no_overwrite():
    """P1-1: two tools sharing an event_id must keep separate edges.

    Before the composite PK, the second tool's ``upsert_event_edges`` silently
    replaced the first tool's row, corrupting the topology tree.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)

        claude_evt = _make_event(
            event_id="e1", session_id="sc", parent_event_id="p-claude", source="claude"
        )
        codex_evt = _make_event(
            event_id="e1", session_id="sx", parent_event_id="p-codex", source="codex"
        )
        storage.insert_event(claude_evt)
        storage.insert_event(codex_evt)
        storage.upsert_event_edges([claude_evt, codex_evt])

        # Composite PK (source, event_id) keeps both rows — not one overwritten.
        count = storage.conn.execute(
            "SELECT COUNT(*) FROM event_edges WHERE event_id='e1'"
        ).fetchone()[0]
        assert count == 2, f"expected 2 edges for shared event_id, got {count}"

        claude_edges = storage.get_event_edges("sc", "claude")
        codex_edges = storage.get_event_edges("sx", "codex")
        assert len(claude_edges) == 1 and claude_edges[0]["event_id"] == "e1"
        assert len(codex_edges) == 1 and codex_edges[0]["event_id"] == "e1"
        # Each edge belongs to its own session, so per-source queries stay isolated
        # (the composite PK is (source, event_id); session_id is the exposed column).
        assert claude_edges[0]["session_id"] == "sc"
        assert codex_edges[0]["session_id"] == "sx"
        storage.close()


def test_session_detail_endpoint_scoped_by_source():
    """P1-2: GET /api/sessions/{id}?source= returns the tool-specific row."""
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)
        storage.conn.execute(
            "INSERT INTO sessions (source, id, summary, message_count, "
            "first_message_at, last_message_at) VALUES "
            "('claude', 'same-id', 'from claude', 1, "
            "'2026-01-01T00:00:00+00:00', '2026-01-02T00:00:00+00:00')"
        )
        storage.conn.execute(
            "INSERT INTO sessions (source, id, summary, message_count, "
            "first_message_at, last_message_at) VALUES "
            "('codex', 'same-id', 'from codex', 1, "
            "'2026-02-01T00:00:00+00:00', '2026-02-02T00:00:00+00:00')"
        )
        storage.conn.commit()
        storage.close()

        client = TestClient(create_app())
        r_claude = client.get("/api/sessions/same-id?source=claude")
        assert r_claude.status_code == 200
        assert r_claude.json()["summary"] == "from claude"

        r_codex = client.get("/api/sessions/same-id?source=codex")
        assert r_codex.status_code == 200
        assert r_codex.json()["summary"] == "from codex"


def test_upsert_session_preserves_earliest_first_message_at():
    """P1-3: incremental syncs must not shift a session's true start time."""
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)

        early = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        mid = datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC)
        late = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)
        later = datetime(2026, 3, 2, 0, 0, 0, tzinfo=UTC)

        # First sync: the session spans early..mid.
        storage.upsert_session(
            Session(
                source="claude",
                session_id="s",
                summary="d",
                first_message_at=early,
                last_message_at=mid,
            )
        )
        # Incremental sync: only a later batch (late..later). first must stay early.
        storage.upsert_session(
            Session(
                source="claude",
                session_id="s",
                summary="d",
                first_message_at=late,
                last_message_at=later,
            )
        )

        sess = storage.get_session("s", "claude")
        assert sess["first_message_at"] == early.isoformat(), sess["first_message_at"]
        assert sess["last_message_at"] == later.isoformat(), sess["last_message_at"]
        storage.close()
