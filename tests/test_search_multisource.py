"""Regression tests for multi-source search correctness and relevance ranking.

These lock in two fixes from the code review:

* F1 — ``search_fts`` must JOIN ``events`` on ``(source, event_id)``, not just
  ``event_id``. Under multi-source, two tools can emit the same event uuid; a
  join on ``event_id`` alone would cross-wire rows between sources.
* F2 — ``bm25(events_fts)`` must reflect content_text relevance. The previous
  ``bm25(events_fts, 0.0, 10.0, 5.0)`` zeroed the content_text weight, so
  results were effectively rowid-ordered (no relevance).
"""

import tempfile
from datetime import UTC, datetime
from pathlib import Path

from bagger.models.event import BlockType, ContentBlock, MemoryEvent, Role
from bagger.storage.sqlite import SqliteStorage


def _ev(event_id, source, session_id, text, blocks=None):
    return MemoryEvent(
        event_id=event_id,
        session_id=session_id,
        source=source,
        timestamp=datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC),
        role=Role.USER,
        content_blocks=blocks or [ContentBlock(block_type=BlockType.TEXT, text=text)],
        cwd="/tmp/proj",
    )


def test_multisource_search_scopes_by_source():
    """Two tools sharing an event uuid must not cross-contaminate search hits."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        storage = SqliteStorage(Path(tmpdir) / "t.db")
        storage.connect()

        storage.insert_event(_ev("shared-id", "claude", "s1", "alpha beta gamma"))
        storage.insert_event(_ev("shared-id", "chatgpt", "s1", "delta epsilon zeta"))

        # Searching the claude source for "alpha" must return ONLY the claude row.
        # (EVENT_COLS does not surface `source`, so we assert on content_text and
        #  row count. The pre-fix bug joined on event_id alone and returned 2 rows
        #  here — one of them the chatgpt event — which this len==1 check rejects.)
        claude_hits = storage.search("alpha", source="claude")
        assert len(claude_hits) == 1
        assert "alpha" in claude_hits[0]["content_text"]

        # And the chatgpt source for "delta" must return ONLY the chatgpt row.
        chatgpt_hits = storage.search("delta", source="chatgpt")
        assert len(chatgpt_hits) == 1
        assert "delta" in chatgpt_hits[0]["content_text"]

        # Un-scoped query for a claude-only term returns just that one row.
        unscoped = storage.search("alpha")
        assert len(unscoped) == 1
        assert "alpha" in unscoped[0]["content_text"]

        storage.close()


def test_search_ranks_by_content_relevance():
    """Higher term frequency in content_text must rank first (bm25 relevance)."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        storage = SqliteStorage(Path(tmpdir) / "t.db")
        storage.connect()

        # One event mentions "python" once, another many times.
        storage.insert_event(_ev("low-freq", "claude", "s1", "python"))
        storage.insert_event(
            _ev("high-freq", "claude", "s2", "python python python python python")
        )

        hits = storage.search("python")
        assert len(hits) == 2
        # The high-frequency event should be the most relevant (ranked first).
        assert hits[0]["event_id"] == "high-freq"

        storage.close()


def test_batch_insert_populates_tool_uses_and_fts():
    """insert_events (batched) must still index tool_uses and FTS rows."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        storage = SqliteStorage(Path(tmpdir) / "t.db")
        storage.connect()

        events = [
            _ev(
                "e1",
                "claude",
                "s1",
                "hello",
                blocks=[
                    ContentBlock(block_type=BlockType.TEXT, text="hello world"),
                    ContentBlock(
                        block_type=BlockType.TOOL_USE,
                        tool_name="Bash",
                        tool_id="t1",
                        tool_input={"cmd": "unique_marker_xyz"},
                    ),
                ],
            ),
            _ev("e2", "claude", "s2", "goodbye"),
        ]
        inserted = storage.insert_events(events)
        assert inserted == 2

        # tool_uses row was written (batched, not per-event).
        assert storage.get_stats()["tool_uses"] == 1

        # FTS indexed the event text, so the batch-inserted event is searchable.
        hits = storage.search("hello")
        assert len(hits) == 1
        assert hits[0]["event_id"] == "e1"

        storage.close()
