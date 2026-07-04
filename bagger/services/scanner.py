"""Session discovery and incremental scanning."""

import contextlib
import json
from pathlib import Path

from bagger.exporters.jsonl import JsonlExporter
from bagger.models.event import Session, WatchState
from bagger.parser.claude import extract_summary, parse_jsonl
from bagger.storage.sqlite import SqliteStorage

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


def discover_sessions(projects_dir: Path | None = None) -> list[Path]:
    """Find all valid Claude Code JSONL session files.

    Excludes agent-* files and files containing 'warmup'.
    """
    projects_dir = projects_dir or CLAUDE_PROJECTS_DIR
    if not projects_dir.exists():
        return []

    files: list[Path] = []
    for root, _, filenames in _walk(projects_dir):
        for name in filenames:
            if (
                name.endswith(".jsonl")
                and not name.startswith("agent-")
                and "warmup" not in name.lower()
            ):
                files.append(Path(root) / name)

    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def _walk(projects_dir: Path):
    """os.walk wrapper (avoiding direct os import in public API)."""
    import os

    yield from os.walk(projects_dir)


def upsert_session_from_events(
    storage: SqliteStorage,
    session_id: str,
    filepath: Path,
    events: list,
) -> None:
    """Upsert session metadata derived from a list of parsed events."""
    summary = extract_summary(filepath)
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
    projects_dir: Path | None = None,
    full: bool = False,
    state_path: Path | None = None,
    jsonl_path: Path | None = None,
) -> dict:
    """Scan all sessions and import events.

    Args:
        storage: Connected SqliteStorage instance.
        projects_dir: Directory containing JSONL files.
        full: If True, reprocess all files from scratch.
        state_path: Path to watch state JSON file for incremental mode.
        jsonl_path: Path for JSONL exporter backup.

    Returns:
        Stats dict with counts.
    """
    state_path = state_path or Path.home() / ".bagger" / "state.json"
    jsonl_path = jsonl_path or Path.home() / ".bagger" / "events.jsonl"

    exporter = JsonlExporter(jsonl_path)
    state = _load_state(state_path) if not full else WatchState()
    files = discover_sessions(projects_dir)

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
                parse_jsonl(filepath)
                if last_offset == 0 or full
                else _parse_new_lines(filepath, last_offset)
            )
        except Exception:
            continue

        if not events:
            continue

        new_count = storage.insert_events(events)
        _export_events(exporter, events)
        upsert_session_from_events(storage, session_id, filepath, events)

        state.sessions[session_id] = file_size

        if new_count > 0:
            stats["sessions"] += 1
            stats["events"] += new_count

    _save_state(state, state_path)
    return stats


def _parse_new_lines(filepath: Path, offset: int) -> list:
    """Parse only new lines appended after a byte offset — no temp file needed."""
    import json as _json

    with open(filepath, encoding="utf-8") as f:
        f.seek(offset)
        new_lines = f.readlines()

    raw_entries = []
    for line in new_lines:
        line = line.strip()
        if not line:
            continue
        try:
            raw = _json.loads(line)
        except _json.JSONDecodeError:
            continue
        if raw.get("type") in ("user", "assistant"):
            raw_entries.append(raw)

    from bagger.parser.claude import _parse_entry

    events = [e for raw in raw_entries if (e := _parse_entry(raw)) is not None]
    return events


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
