"""Verify the event-driven watcher captures Codex rollout transcripts.

The watcher shares its per-file sync pipeline with the scanner
(``SyncService.sync_file``), which keys offsets by ``parser.session_id_for``
— for Codex that is the ``session_meta.id``, NOT the rollout filename's stem.
These tests prove the watcher actually honors that mapping for Codex and
captures live appends incrementally, not by re-parsing the whole file.

Run with the bagger-test venv:
    pytest tests/test_codex_watcher.py -q
"""

import contextlib
import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

from bagger.parsers.codex import CodexParser
from bagger.services.watcher import Watcher
from bagger.storage.sqlite import SqliteStorage

META_ID = "codex-watch-verify-001"
# A filename stem that is deliberately NOT the session id — proves the watcher
# does not key Codex sessions by filename.
ROLL_FILE = "rollout-2026-08-03T09-00-00-0000-abc123.jsonl"


def _storage(tmp_path: Path) -> SqliteStorage:
    storage = SqliteStorage(tmp_path / "bagger.db")
    storage.connect()
    return storage


def _meta(meta_id: str = META_ID) -> dict:
    return {
        "timestamp": "2026-08-03T09:00:00.000Z",
        "type": "session_meta",
        "payload": {
            "id": meta_id,
            "cwd": "/home/gc/proj",
            "model_provider": "openai",
            "originator": "Codex Desktop",
            "git": {"branch": "main"},
        },
    }


def _user(text: str) -> dict:
    return {
        "timestamp": "2026-08-03T09:00:01.000Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": text}],
        },
    }


def _assistant(text: str) -> dict:
    return {
        "timestamp": "2026-08-03T09:00:02.000Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": text}],
        },
    }


def _write_rollout(path: Path, *lines: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")


def _append_line(path: Path, line: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def _patched_watcher(storage, codex_home: Path, tmp_path: Path, source: str = "codex") -> Watcher:
    """A Watcher whose CodexParser is redirected at a temp home (no real ~/.codex)."""
    codex = CodexParser(codex_home=codex_home)
    ctx = patch.multiple(
        "bagger.services.watcher.ParserRegistry",
        get=lambda s=None: codex,
        all_parsers=lambda: [codex],
    )
    ctx.__enter__()
    watcher = Watcher(storage, source=source, state_path=tmp_path / "state.json")
    watcher._patch_ctx = ctx  # type: ignore[attr-defined]
    return watcher


def _stop_watcher(watcher: Watcher) -> None:
    watcher._running = False
    with contextlib.suppress(Exception):
        watcher._wake.put_nowait(None)
    ctx = getattr(watcher, "_patch_ctx", None)
    if ctx is not None:
        ctx.__exit__(None, None, None)


def _wait_for(predicate, timeout: float = 10.0, step: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


# ── A. Watcher keys Codex sessions by session_meta.id, not filename ──


def test_watcher_keys_session_by_meta_id_not_filename(tmp_path):
    codex_home = tmp_path / "codex_home"
    roll = codex_home / "sessions" / "2026" / "08" / "03" / ROLL_FILE
    _write_rollout(roll, _meta(), _user("why is the test flaky"))

    storage = _storage(tmp_path)
    watcher = _patched_watcher(storage, codex_home, tmp_path)
    try:
        watcher._poll()  # initial scan path (same code the live watcher runs)
    finally:
        _stop_watcher(watcher)

    # Session exists under the real id...
    assert storage.get_session(META_ID, "codex") is not None
    # ...and NOT under the filename stem (this would be the Claude assumption bug).
    assert storage.get_session("rollout-2026-08-03T09-00-00-0000-abc123", "codex") is None
    assert storage.get_event_count(META_ID, "codex") == 1


# ── B. Live append is captured incrementally (parse_incremental, not full) ──


def test_watcher_captures_append_incrementally(tmp_path):
    codex_home = tmp_path / "codex_home"
    roll = codex_home / "sessions" / "2026" / "08" / "03" / ROLL_FILE
    _write_rollout(roll, _meta(), _user("first"), _assistant("draft one"))

    storage = _storage(tmp_path)
    watcher = _patched_watcher(storage, codex_home, tmp_path)
    try:
        # Spy on which parse method the pipeline uses, to prove incremental resume.
        calls: list = []
        real_parse = watcher.parser.parse
        real_inc = watcher.parser.parse_incremental
        watcher.parser.parse = lambda p: (calls.append(("full", 0)), real_parse(p))[1]
        watcher.parser.parse_incremental = lambda p, o: (
            calls.append(("inc", o)),
            real_inc(p, o),
        )[1]

        watcher._poll()
        assert storage.get_event_count(META_ID, "codex") == 2
        assert ("full", 0) in calls  # first sight => full parse

        # Codex appends a new turn to the live rollout file.
        _append_line(roll, _assistant("draft two (incremental)"))
        watcher._sync_path(roll, "codex", reset=False)

        assert storage.get_event_count(META_ID, "codex") == 3
        # The resume used incremental parse from a non-zero byte offset.
        assert any(kind == "inc" and off > 0 for kind, off in calls)
    finally:
        _stop_watcher(watcher)


# ── C. True event-driven capture: a live OS-level append is picked up ──


def test_watcher_captures_live_append_event_driven(tmp_path):
    codex_home = tmp_path / "codex_home"
    roll = codex_home / "sessions" / "2026" / "08" / "03" / ROLL_FILE
    _write_rollout(roll, _meta(), _user("bootstrap question"))

    storage = _storage(tmp_path)
    watcher = _patched_watcher(storage, codex_home, tmp_path)
    # rescan_interval=0 isolates event-driven capture (no periodic safety-net).
    thread = threading.Thread(
        target=watcher.watch,
        kwargs={"debounce": 0.2, "interval": 0.1, "rescan_interval": 0.0},
        daemon=True,
    )
    try:
        thread.start()
        # Initial poll (inside watch()) should have indexed the pre-existing file.
        assert _wait_for(lambda: storage.get_event_count(META_ID, "codex") >= 1, timeout=5)

        # Now Codex writes a new turn — a real filesystem modification event.
        _append_line(roll, _assistant("captured in real time"))
        captured = _wait_for(lambda: storage.get_event_count(META_ID, "codex") >= 2, timeout=10)
        assert captured, "watcher did not capture the live append via filesystem events"
        assert storage.get_session(META_ID, "codex") is not None
    finally:
        _stop_watcher(watcher)
        thread.join(timeout=10)
