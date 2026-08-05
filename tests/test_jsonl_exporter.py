"""Tests for the JSONL exporter (bagger.exporters.jsonl)."""

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from bagger.exporters.jsonl import JsonlExporter
from bagger.models.event import (
    BlockType,
    ContentBlock,
    MemoryEvent,
    Role,
)


def _make_event(event_id: str = "evt-1") -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        session_id="sess-1",
        timestamp=datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC),
        role=Role.USER,
        content_blocks=[ContentBlock(block_type=BlockType.TEXT, text="hello")],
        token_input=1,
        token_output=2,
    )


def test_export_writes_one_json_line_per_event():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        path = Path(tmpdir) / "out.jsonl"
        exporter = JsonlExporter(path)
        exporter.export_event(_make_event("a"))
        exporter.export_event(_make_event("b"))
        exporter.close()

        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        loaded = [json.loads(line) for line in lines]
        assert {e["event_id"] for e in loaded} == {"a", "b"}


def test_flush_persists_and_close_is_idempotent():
    """The exporter keeps the file handle open for sequential writes; close()
    must flush and be safe to call multiple times without error or data loss."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        path = Path(tmpdir) / "out.jsonl"
        exporter = JsonlExporter(path)
        exporter.export_event(_make_event("a"))
        exporter.close()
        exporter.close()  # second close must be a no-op

        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1


def test_handle_released_after_close():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        path = Path(tmpdir) / "out.jsonl"
        exporter = JsonlExporter(path)
        exporter.export_event(_make_event("a"))
        exporter.close()

        # File handle released: reopening for read must succeed immediately.
        with path.open("r", encoding="utf-8") as f:
            assert len(f.read().splitlines()) == 1
