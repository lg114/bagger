"""Session discovery and incremental scanning.

Uses ParserRegistry so adding a new AI tool source only requires
registering a new Parser --- no scanner changes needed.

The per-file sync pipeline (discover → parse → insert → export → upsert
→ advance offset) lives in ``bagger.services.sync.SyncService``. This
module is the batch driver: it loads/persists ``WatchState``, iterates
files, and delegates each file to ``SyncService``.
"""

import logging
from pathlib import Path

from bagger.cjk import JIEBA_CJK_WARNING, contains_cjk, jieba_available
from bagger.config import settings
from bagger.models.event import WatchState
from bagger.parsers import ParserRegistry
from bagger.parsers.base import Parser
from bagger.services.sync import SyncError, SyncService
from bagger.services.watch_state_io import load_watch_state, save_watch_state
from bagger.storage.base import Storage

logger = logging.getLogger(__name__)


def _incoming_contains_cjk(parser: Parser, files: list[Path] | None = None) -> bool:
    """Sample the first discovered transcript for CJK content.

    Used by the jieba guard: if jieba is missing and an incoming source
    contains Chinese/Japanese/Korean text, its search index will be broken.
    Parses only the first file's first events to stay cheap.
    """
    if files is None:
        try:
            files = parser.discover_sessions()
        except Exception:
            return False
    if not files:
        return False
    try:
        sample = parser.parse(files[0])[:20]
    except Exception:
        return False
    for event in sample:
        for block in event.content_blocks:
            if block.text and contains_cjk(block.text):
                return True
    return False


def check_jieba_cjk_incoming(parser: Parser, files: list[Path] | None = None) -> str | None:
    """Return a warning if jieba is unavailable but ``parser`` yields CJK text."""
    if jieba_available() or not _incoming_contains_cjk(parser, files):
        return None
    return JIEBA_CJK_WARNING


def scan_all(
    storage: Storage,
    *,
    source: str | None = None,
    full: bool = False,
    state_path: Path | None = None,
    jsonl_path: Path | None = None,
    commit_every: int = 50,
) -> dict:
    """Scan all sessions from registered parser source(s) and import events.

    Multi-tool support (§5.5): when ``source`` is ``None`` (the default), every
    registered parser is driven in turn so a newly added AI tool is picked up
    automatically — no scanner changes needed. Pass a specific ``source`` to
    limit the scan to one tool (e.g. ``"claude"``).

    Args:
        storage: Connected storage instance (satisfies SessionRepository + EventRepository).
        source: Parser source name, or ``None`` to scan *all* registered sources.
        full: If True, reprocess all files from scratch.
        state_path: Path to watch state JSON file for incremental mode.
        jsonl_path: Path for JSONL exporter backup.
        commit_every: Batch size for the bulk transaction — commits at most once
            per this many files (see ``Storage.bulk_write``). Larger = faster for
            huge imports, at the cost of coarser crash-recovery granularity.

    Returns:
        Stats dict with counts, including an ``errors`` key for files that
        failed to parse (no longer swallowed silently).
    """
    state_path = state_path or settings.state_path
    jsonl_path = jsonl_path or settings.jsonl_path

    # §5.5: drive every registered parser (or just one when source is given).
    parsers = [ParserRegistry.get(source)] if source else ParserRegistry.all_parsers()

    state = _load_state(state_path) if not full else WatchState()
    stats = {"sessions": 0, "events": 0, "skipped": 0, "errors": 0}

    # Batch the whole scan into a few transactions instead of one-per-file:
    # ``bulk_write`` defers repo commits and ``sync_file`` calls ``flush()`` after
    # each file, so we only fsync every ``commit_every`` files (plus a final flush
    # on exit). The incremental watcher does NOT use this and commits per file.
    with storage.bulk_write(commit_every=commit_every):
        for parser in parsers:
            files = parser.discover_sessions()
            warn = check_jieba_cjk_incoming(parser, files)
            if warn:
                logger.warning("⚠️  %s", warn)
            sync = SyncService(storage, parser, jsonl_path=jsonl_path)
            for filepath in files:
                try:
                    result = sync.sync_file(filepath, state.sessions, full=full, upsert_always=True)
                except SyncError as exc:
                    stats["errors"] += 1
                    logger.error("Skipping %s during scan: %s", exc.filepath, exc.error)
                    continue
                if result.skipped:
                    stats["skipped"] += 1
                    continue
                if result.new_count > 0:
                    stats["sessions"] += 1
                    stats["events"] += result.new_count
            sync.close()

    _save_state(state, state_path)
    return stats


def _load_state(path: Path) -> WatchState:
    return load_watch_state(path)


def _save_state(state: WatchState, path: Path) -> None:
    save_watch_state(state, path)
