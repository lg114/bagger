"""Session discovery and incremental scanning."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from bagger.exporters.jsonl import JsonlExporter
from bagger.models.event import WatchState
from bagger.parser.claude import parse_jsonl, extract_summary
from bagger.storage.sqlite import SqliteStorage


CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


def discover_sessions(projects_dir: Optional[Path] = None) -> list[Path]:
    """Find all valid Claude Code JSONL session files.

    Excludes agent-* files and files containing 'warmup'.
    """
    if projects_dir is None:
        projects_dir = CLAUDE_PROJECTS_DIR

    if not projects_dir.exists():
        return []

    files: list[Path] = []
    for root, _, filenames in os.walk(projects_dir):
        for name in filenames:
            if not name.endswith(".jsonl"):
                continue
            if name.startswith("agent-"):
                continue
            if "warmup" in name.lower():
                continue
            files.append(Path(root) / name)

    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def scan_all(
    storage: SqliteStorage,
    projects_dir: Optional[Path] = None,
    full: bool = False,
    state_path: Optional[Path] = None,
    jsonl_path: Optional[Path] = None,
) -> dict:
    """Scan all sessions and import events.

    Args:
        storage: Connected SqliteStorage instance.
        projects_dir: Directory containing JSONL files.
        full: If True, reprocess all files from scratch.
        state_path: Path to watch state JSON file for incremental mode.
        jsonl_path: Path for JSONL exporter backup. Defaults to ~/.bagger/events.jsonl.

    Returns:
        Stats dict with counts.
    """
    if state_path is None:
        state_path = Path.home() / ".bagger" / "state.json"
    if jsonl_path is None:
        jsonl_path = Path.home() / ".bagger" / "events.jsonl"

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
            if last_offset == 0 or full:
                events = parse_jsonl(filepath)
            else:
                events = _read_from_offset(filepath, last_offset)
        except Exception:
            continue

        if not events:
            continue

        new_count = storage.insert_events(events)
        _export_events(exporter, events)

        summary = extract_summary(filepath)
        first_ts = events[0].timestamp
        last_ts = events[-1].timestamp
        project_path = events[0].cwd or ""

        from bagger.models.event import Session

        session = Session(
            session_id=session_id,
            summary=summary,
            project_path=project_path,
            message_count=storage.get_event_count(session_id),
            first_message_at=first_ts,
            last_message_at=last_ts,
        )
        storage.upsert_session(session)

        state.sessions[session_id] = file_size

        if new_count > 0:
            stats["sessions"] += 1
            stats["events"] += new_count

    _save_state(state, state_path)
    return stats


def _read_from_offset(filepath: Path, offset: int) -> list:
    """Read only new lines from a JSONL file starting at byte offset."""
    from bagger.parser.claude import parse_jsonl as _parse

    with open(filepath, "r", encoding="utf-8") as f:
        f.seek(offset)
        new_content = f.read()

    if not new_content:
        return []

    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(new_content)
        tmp_path = tmp.name

    try:
        return _parse(Path(tmp_path))
    finally:
        os.unlink(tmp_path)


def _load_state(path: Path) -> WatchState:
    if not path.exists():
        return WatchState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return WatchState(**data)
    except Exception:
        return WatchState()


def _save_state(state: WatchState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.model_dump_json(indent=2), encoding="utf-8")


def _export_events(exporter, events: list) -> None:
    """Export events to JSONL backup, ignoring errors."""
    for ev in events:
        try:
            exporter.export_event(ev)
        except Exception:
            pass
