"""Session discovery and incremental scanning.

Uses ParserRegistry so adding a new AI tool source only requires
registering a new Parser --- no scanner changes needed.

The per-file sync pipeline (discover → parse → insert → export → upsert
→ advance offset) lives in ``bagger.services.sync.SyncService``. This
module is the batch driver: it loads/persists ``WatchState``, iterates
files, and delegates each file to ``SyncService``.
"""

import json
from pathlib import Path

from bagger.config import settings
from bagger.models.event import WatchState
from bagger.parser import ParserRegistry
from bagger.services.sync import SyncService

# Backward-compat re-export: watcher.py and any external callers imported this
# from scanner before SyncService existed. Keep the name alive to avoid breakage.
from bagger.services.sync import (
    upsert_session_from_events as upsert_session_from_events,  # noqa: F401
)
from bagger.storage.base import Storage


def scan_all(
    storage: Storage,
    *,
    source: str = "claude",
    full: bool = False,
    state_path: Path | None = None,
    jsonl_path: Path | None = None,
) -> dict:
    """Scan all sessions from a registered parser source and import events.

    Args:
        storage: Connected storage instance (satisfies SessionRepository + EventRepository).
        source: Parser source name (default "claude").
        full: If True, reprocess all files from scratch.
        state_path: Path to watch state JSON file for incremental mode.
        jsonl_path: Path for JSONL exporter backup.

    Returns:
        Stats dict with counts.
    """
    parser = ParserRegistry.get(source)
    state_path = state_path or settings.state_path
    jsonl_path = jsonl_path or settings.jsonl_path

    sync = SyncService(storage, parser, jsonl_path=jsonl_path)
    state = _load_state(state_path) if not full else WatchState()
    files = parser.discover_sessions()

    stats = {"sessions": 0, "events": 0, "skipped": 0}

    for filepath in files:
        result = sync.sync_file(filepath, state.sessions, full=full, upsert_always=True)
        if result is None:
            continue  # parse error swallowed
        if result.skipped:
            stats["skipped"] += 1
            continue
        if result.new_count > 0:
            stats["sessions"] += 1
            stats["events"] += result.new_count

    _save_state(state, state_path)
    sync.close()
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
