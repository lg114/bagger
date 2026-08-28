"""Regression tests for scan robustness / performance fixes.

Covers four defects found by the real-data E2E verification round
(.workbuddy/verify/):

1. FTS delete-by-UNINDEXED-column was O(N²): one full events_fts scan per
   event. Re-inserting the same events must stay fast and leave exactly one
   FTS row per event.
2. A full re-scan re-exported every event to the JSONL backup, doubling it on
   each ``scan --full``. Only genuinely-new events may be exported.
3. ``GET /api/sessions/{id}/tree`` returned 500 on long linear sessions
   (>1000-deep parent chains) — json.dumps recursion limit.
4. A single undecodable byte in a Claude JSONL killed the whole file's parse
   (text-mode open); valid lines around it must be salvaged.
"""

import gc
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from bagger.api.app import create_app
from bagger.config import Settings
from bagger.models.event import BlockType, ContentBlock, MemoryEvent, Role, Session
from bagger.parsers.claude import ClaudeParser
from bagger.services.sync import SyncService
from bagger.storage.sqlite import SqliteStorage

# ── shared helpers ──────────────────────────────────────────


def _make_event(event_id: str, session_id: str = "s1", text: str = "hello") -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        session_id=session_id,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        role=Role.USER,
        content_blocks=[ContentBlock(block_type=BlockType.TEXT, text=text)],
        source="claude",
    )


def _open_storage(tmpdir: str) -> SqliteStorage:
    storage = SqliteStorage(Path(tmpdir) / "test.db")
    storage.connect()
    return storage


def _write_transcript(projects_dir: Path, name: str, entries: list[bytes | str]) -> Path:
    """Write a raw transcript file; bytes entries are written verbatim."""
    session_dir = projects_dir / "projhash"
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / name
    with open(path, "wb") as f:
        for entry in entries:
            f.write(entry if isinstance(entry, bytes) else entry.encode("utf-8"))
            f.write(b"\n")
    return path


def _user_line(n: int) -> str:
    return json.dumps(
        {
            "type": "user",
            "timestamp": "2026-06-30T06:00:00.000Z",
            "sessionId": "sess-1",
            "cwd": "/tmp/project",
            "message": {"role": "user", "content": f"message {n}"},
            "uuid": f"evt-{n}",
            "parentUuid": f"evt-{n - 1}" if n > 1 else None,
        }
    )


# ── 1. FTS dedupe / existing_event_ids ─────────────────────


def test_insert_events_twice_leaves_one_fts_row_per_event():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        storage = _open_storage(tmpdir)
        try:
            events = [_make_event(f"e{i}") for i in range(5)]
            storage.insert_events(events)
            storage.insert_events(events)  # re-insert (upsert path)

            n_events = storage._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            n_fts = storage._conn.execute("SELECT COUNT(*) FROM events_fts").fetchone()[0]
            assert n_events == 5
            assert n_fts == 5, f"expected 5 FTS rows, got {n_fts}"

            # search still returns exactly one row per event
            results = storage.search("hello")
            assert len(results) == 5
        finally:
            storage.close()
            gc.collect()


def test_existing_event_ids_returns_subset():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        storage = _open_storage(tmpdir)
        try:
            storage.insert_events([_make_event(f"e{i}") for i in range(3)])
            found = storage.existing_event_ids("claude", ["e0", "e1", "e9", "e2", "e9"])
            assert found == {"e0", "e1", "e2"}
            assert storage.existing_event_ids("claude", []) == set()
            assert storage.existing_event_ids("codex", ["e0"]) == set()
        finally:
            storage.close()
            gc.collect()


def test_existing_event_ids_handles_large_batches():
    """Chunked IN-lookups must cover >500 ids (parameter limit safety)."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        storage = _open_storage(tmpdir)
        try:
            ids = [f"e{i}" for i in range(1200)]
            storage.insert_events([_make_event(i) for i in ids])
            found = storage.existing_event_ids("claude", ids + ["zzz"])
            assert len(found) == 1200
            assert "zzz" not in found
        finally:
            storage.close()
            gc.collect()


# ── 2. JSONL backup dedupe on full re-scan ─────────────────


def test_full_resync_does_not_duplicate_jsonl_backup():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        storage = _open_storage(tmpdir)
        projects_dir = Path(tmpdir) / "projects"
        projects_dir.mkdir()
        parser = ClaudeParser(projects_dir=projects_dir)
        jsonl_path = Path(tmpdir) / "events.jsonl"
        sync = SyncService(storage, parser, jsonl_path=jsonl_path)
        path = _write_transcript(projects_dir, "sess-1.jsonl", [_user_line(i) for i in range(1, 6)])
        try:
            # close() flushes the buffered exporter handle; it re-opens
            # lazily on the next export, so further syncs still work.
            sync.sync_file(path, {})
            sync.close()
            first_lines = jsonl_path.read_text(encoding="utf-8").splitlines()
            assert len(first_lines) == 5

            # full re-sync: same file, forced re-parse — backup must NOT grow
            sync.sync_file(path, {}, full=True)
            sync.close()
            second_lines = jsonl_path.read_text(encoding="utf-8").splitlines()
            assert len(second_lines) == 5, (
                f"full re-scan re-exported events: {len(second_lines)} lines"
            )

            # appending a new event to the file exports only that event
            with open(path, "a", encoding="utf-8") as f:
                f.write(_user_line(6) + "\n")
            sync.sync_file(path, {}, full=True)
            sync.close()
            third_lines = jsonl_path.read_text(encoding="utf-8").splitlines()
            assert len(third_lines) == 6
        finally:
            sync.close()
            storage.close()
            gc.collect()


# ── 3. /tree endpoint on deep linear chains ────────────────


def test_tree_endpoint_survives_deep_linear_chain():
    """A >1000-deep parent chain must serialize, not 500 on json.dumps."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        import bagger.config as config

        original = config.settings
        config.settings = Settings(bagger_dir=Path(tmpdir))
        # The API's get_storage reads settings.db_path — use that exact path
        # so the TestClient below sees this DB.
        storage = SqliteStorage(config.settings.db_path)
        storage.connect()
        try:
            n = 1500
            events = [
                MemoryEvent(
                    event_id=f"deep-{i:05d}",
                    session_id="s-deep",
                    parent_event_id=f"deep-{i - 1:05d}" if i else None,
                    timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                    role=Role.USER,
                    content_blocks=[ContentBlock(block_type=BlockType.TEXT, text="x")],
                    source="claude",
                )
                for i in range(n)
            ]
            storage.insert_events(events)
            storage.upsert_event_edges(events)
            storage.upsert_session(
                Session(source="claude", session_id="s-deep", summary="deep", message_count=n)
            )
            storage._conn.commit()
        finally:
            storage.close()
            gc.collect()

        from fastapi.testclient import TestClient

        try:
            client = TestClient(create_app())
            resp = client.get("/api/sessions/s-deep/tree", params={"source": "claude"})
            assert resp.status_code == 200, resp.text[:200]
            # json.loads also recurses per nesting level (C limit), so verify
            # the payload textually: shape, node count, and max bracket depth
            # via an iterative in-string-aware scan.
            raw = resp.text
            assert raw.startswith('{"data":[') and raw.endswith("]}")
            assert raw.count('"event_id":"deep-') == 1500
            in_str = esc = False
            depth = max_depth = 0
            for ch in raw:
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                elif ch == '"':
                    in_str = True
                elif ch in "[{":
                    depth += 1
                    max_depth = max(max_depth, depth)
                elif ch in "]}":
                    depth -= 1
            # 1 root node with a 1500-deep chain: {"data": [ node {...} ]}
            assert max_depth >= 1500, max_depth
            # all brackets balanced == structurally well-formed JSON
            assert depth == 0, depth
        finally:
            config.settings = original


# ── 4. corrupt / undecodable transcript lines ──────────────


def test_undecodable_bytes_do_not_kill_the_whole_file():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        projects_dir = Path(tmpdir) / "projects"
        path = _write_transcript(
            projects_dir,
            "corrupt.jsonl",
            [
                _user_line(1),
                b"\xff\xfe\x00 binary garbage \x00\xff",  # undecodable line
                "this is not json {{{",  # invalid JSON
                _user_line(2),
                '{"type": "user", "uuid": null, "sessionId": null}',  # unusable keys
                _user_line(3),
            ],
        )
        parser = ClaudeParser(projects_dir=projects_dir)
        events = parser.parse(path)
        ids = [e.event_id for e in events]
        assert ids == ["evt-1", "evt-2", "evt-3"]

        # incremental parse from 0 behaves the same way
        events_inc = parser.parse_incremental(path, 0)
        assert [e.event_id for e in events_inc] == ids


def test_extract_summary_survives_garbage_first_line():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        projects_dir = Path(tmpdir) / "projects"
        path = _write_transcript(
            projects_dir,
            "summary.jsonl",
            [
                b"\xff\xfe garbage",
                _user_line(1),
            ],
        )
        parser = ClaudeParser(projects_dir=projects_dir)
        assert parser.extract_summary(path) == "message 1"


def test_sync_of_corrupt_file_still_imports_valid_lines():
    """End-to-end: SyncService over a mixed file imports the good events."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        storage = _open_storage(tmpdir)
        projects_dir = Path(tmpdir) / "projects"
        path = _write_transcript(
            projects_dir, "mixed.jsonl", [b"\x00\xff bad", _user_line(1), _user_line(2)]
        )
        parser = ClaudeParser(projects_dir=projects_dir)
        sync = SyncService(storage, parser, jsonl_path=Path(tmpdir) / "events.jsonl")
        try:
            result = sync.sync_file(path, {})
            assert result.new_count == 2
        finally:
            sync.close()
            storage.close()
            gc.collect()


def test_empty_transcript_file_is_noop():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        storage = _open_storage(tmpdir)
        projects_dir = Path(tmpdir) / "projects"
        path = _write_transcript(projects_dir, "empty.jsonl", [])
        parser = ClaudeParser(projects_dir=projects_dir)
        sync = SyncService(storage, parser, jsonl_path=Path(tmpdir) / "events.jsonl")
        try:
            result = sync.sync_file(path, {})
            assert result.new_count == 0
            # A 0-byte file satisfies "offset >= file size", so it counts as
            # unchanged and is skipped — no error, no import.
            assert result.skipped
        finally:
            sync.close()
            storage.close()
            gc.collect()
