"""Real-time watcher: poll for new JSONL lines and sync incrementally.

The per-file sync pipeline (discover → parse → insert → export → upsert
→ advance offset) lives in ``bagger.services.sync.SyncService``. This
module is the polling driver: it discovers session files and delegates
each file to ``SyncService``.
"""

import json
import logging
import signal
import time
from pathlib import Path

from bagger.config import settings
from bagger.models.event import WatchState
from bagger.parsers import ParserRegistry
from bagger.services.sync import SyncError, SyncService
from bagger.storage.base import Storage

logger = logging.getLogger(__name__)


def _load_state(path: Path) -> WatchState:
    if not path.exists():
        return WatchState()
    try:
        return WatchState(**json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        logger.warning("Could not read watch state %s; starting fresh", path, exc_info=True)
        return WatchState()


def _save_state(state: WatchState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.model_dump_json(indent=2), encoding="utf-8")


class Watcher:
    """Polling-based file watcher for AI coding tool JSONL transcripts.

    Each poll cycle discovers session files via ``ParserRegistry`` and
    delegates per-file syncing to ``SyncService``.  Adding a new AI tool
    source only requires registering a new Parser — no watcher changes.

    Offsets are persisted to ``state.json`` (mirroring the scanner) so a
    crash or restart resumes incrementally instead of re-parsing every file
    from byte 0.
    """

    def __init__(
        self,
        storage: Storage,
        source: str | None = None,
        state_path: Path | None = None,
        save_interval: float = 5.0,
    ):
        self.storage = storage
        # §5.5: drive every registered parser by default. ``source`` limits the
        # watcher to a single tool. ``self._syncs`` maps source_name -> SyncService
        # so each tool gets its own per-file pipeline. For the single-source and
        # no-source cases we also expose ``self.parser`` / ``self._sync`` pointing
        # at the (first) parser/service, keeping the historical attributes and
        # the existing tests that poke them directly.
        if source is not None:
            parser = ParserRegistry.get(source)
            self._sources = [parser]
        else:
            self._sources = ParserRegistry.all_parsers()
        self._syncs = {p.source_name: SyncService(storage, p) for p in self._sources}
        # Convenience aliases (single-source shape); point at the first entry.
        self.parser = self._sources[0] if self._sources else None
        self._sync = self._syncs[self.parser.source_name] if self.parser else None

        self._state_path = state_path or settings.state_path
        # Resume from persisted offsets; live updates happen in ``_poll``.
        self._state = _load_state(self._state_path)
        self._offsets: dict[str, int] = self._state.sessions
        self._failed: set[tuple[str, str]] = set()
        self._running = False
        self._closed = False
        self._last_save = 0.0
        self._save_interval = save_interval

    def watch(self, interval: float = 1.0) -> None:
        """Start watching. Runs until stopped via SIGINT/SIGTERM or Ctrl+C."""
        self._running = True

        signal.signal(signal.SIGINT, self._on_stop)
        signal.signal(signal.SIGTERM, self._on_stop)

        names = ", ".join(p.source_name for p in self._sources) or "(no parsers registered)"
        print(f"Watching {names} transcripts ...")
        print("Press Ctrl+C to stop\n")

        try:
            while self._running:
                try:
                    self._poll()
                    self._maybe_persist_offsets()
                    time.sleep(interval)
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    logger.warning("Watch cycle error (continuing): %s", e, exc_info=True)
        finally:
            # Always release the exporter file handle, even when interrupted.
            # Without this the watcher leaks the handle for its entire
            # (long-running) lifetime.
            self._persist_offsets()
            self.close()
            print("\nWatcher stopped.")

    def close(self) -> None:
        """Release sync resources (exporter file handles).

        Idempotent: safe to call from both ``watch()``'s ``finally`` block and
        the context-manager ``__exit__`` (e.g. ``with Watcher(...) as w``).
        The storage connection is owned by the caller (CLI's ``with_storage``).
        """
        if self._closed:
            return
        for sync in self._syncs.values():
            sync.close()
        self._closed = True

    def __enter__(self) -> "Watcher":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _poll(self) -> None:
        for source_name, sync in self._syncs.items():
            parser = sync.parser
            files = parser.discover_sessions()

            for filepath in files:
                session_id = filepath.stem
                if (source_name, session_id) in self._failed:
                    continue  # already logged a parse error this run; avoid spam
                try:
                    result = sync.sync_file(filepath, self._offsets, upsert_always=False)
                except SyncError as exc:
                    self._failed.add((source_name, session_id))
                    logger.error(
                        "Parse failed for %s — skipping for the rest of this run. "
                        "Fix the file and restart the watcher to retry.",
                        exc.filepath,
                    )
                    continue
                if result.skipped:
                    continue

                # Only report when new events were inserted (watcher prints).
                if result.new_count > 0:
                    if result.is_first_sight:
                        summary = parser.extract_summary(filepath)
                        print(f'  [new] session {session_id[:8]} "{summary}"')
                    print(f"    +{result.new_count} events synced")

    # -- offset persistence --------------------------------------

    def _maybe_persist_offsets(self) -> None:
        """Persist offsets at most every ``save_interval`` seconds."""
        now = time.monotonic()
        if now - self._last_save >= self._save_interval:
            self._persist_offsets()
            self._last_save = now

    def _persist_offsets(self) -> None:
        """Atomically save current offsets to ``state.json``."""
        self._state.sessions = self._offsets
        try:
            _save_state(self._state, self._state_path)
        except OSError:
            logger.warning("Failed to persist watch state %s", self._state_path, exc_info=True)

    def _on_stop(self, signum, frame):
        self._running = False
        del signum, frame
