"""Session discovery and incremental scanning.

Uses ParserRegistry so adding a new AI tool source only requires
registering a new Parser --- no scanner changes needed.
"""

import contextlib
import json
from pathlib import Path

from bagger.exporters.jsonl import JsonlExporter
from bagger.models.event import Session, WatchState
from bagger.parser import Parser, ParserRegistry
from bagger.storage.sqlite import SqliteStorage


def upsert_session_from_events(
    storage: SqliteStorage,
    parser: Parser,
    session_id: str,
    filepath: Path,
    events: list,
) -> None:
    """Upsert session metadata derived from a list of parsed events."""
    summary = parser.extract_summary(filepath)
    first_ts = events[0].timestamp
    last_ts = events[-1].timestamp
    project_path = events[0].cwd or ""

    storage.upsert_session(
        Session(
            session_id=session_id,
            summary=summary,
            project_path=project_path,
            message_count=storage.get_event_count(session_id),
            first_message_at=first_ts,
            last_message_at=last_ts,
        )
    )


def scan_all(
    storage: SqliteStorage,
    *,
    source: str = "claude",
    full: bool = False,
    state_path: Path | None = None,
    jsonl_path: Path | None = None,
) -> dict:
    """Scan all sessions from a registered parser source and import events.

    Args:
        storage: Connected SqliteStorage instance.
        source: Parser source name (default "claude").
        full: If True, reprocess all files from scratch.
        state_path: Path to watch state JSON file for incremental mode.
        jsonl_path: Path for JSONL exporter backup.

    Returns:
        Stats dict with counts.
    """
    parser = ParserRegistry.get(source)
    state_path = state_path or Path.home() / ".bagger" / "state.json"
    jsonl_path = jsonl_path or Path.home() / ".bagger" / "events.jsonl"

    exporter = JsonlExporter(jsonl_path)
    state = _load_state(state_path) if not full else WatchState()
    files = parser.discover_sessions()

    stats = {"sessions": 0, "events": 0, "skipped": 0}

    for filepath in files:
        session_id = filepath.stem
        file_size = filepath.stat().st_size
        last_offset = state.sessions.get(session_id, 0)

        if not full and last_offset >= file_size:
            stats["skipped"] += 1
            continue

        try:
            events = (
                parser.parse(filepath)
                if last_offset == 0 or full
                else parser.parse_incremental(filepath, last_offset)
            )
        except Exception:
            continue

        if not events:
            continue

        new_count = storage.insert_events(events)
        _export_events(exporter, events)
        upsert_session_from_events(storage, parser, session_id, filepath, events)

        state.sessions[session_id] = file_size

        if new_count > 0:
            stats["sessions"] += 1
            stats["events"] += new_count

    _save_state(state, state_path)
    return stats


def _load_state(path: Path) -> WatchState:
    if not path.exists():
        return WatchState()
    try:
        return WatchState(**json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return WatchState()


def _save_state(state: WatchState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.model_dump_json(indent=2), encoding="utf-8")


def _export_events(exporter, events: list) -> None:
    """Export events to JSONL backup, ignoring errors."""
    for ev in events:
        with contextlib.suppress(Exception):
            exporter.export_event(ev)
