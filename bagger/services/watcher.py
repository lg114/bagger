"""Real-time watcher: sync JSONL transcripts as they change on disk.

The per-file sync pipeline (discover → parse → insert → export → upsert
→ advance offset) lives in ``bagger.services.sync.SyncService``. This module
is the *driver*: it used to poll every second (``1s full scan``), which is
wasteful once transcripts grow — every cycle re-traverses the whole projects
tree even when nothing changed.

It is now **event-driven** via `watchdog`: a filesystem observer watches each
parser's ``watch_root()`` directory and enqueues only the specific files that
actually changed. A small main-loop debounce coalesces the burst of events a
live session emits while it is mid-write, so a file appended 50 times in 200ms
is synced once, not 50 times.

All database work still happens on the **main thread** (the thread that owns
the sqlite connection — sqlite connections are not thread-safe, see the A1
fix). The observer thread only enqueues paths; it never touches storage.
"""

import contextlib
import logging
import queue
import signal
import sys
import threading
import time
from pathlib import Path

from bagger.config import settings
from bagger.models.event import WatchState
from bagger.parsers import ParserRegistry
from bagger.services.sync import SyncError, SyncService
from bagger.services.watch_state_io import load_watch_state, save_watch_state
from bagger.storage.base import Storage

logger = logging.getLogger(__name__)

# watchdog is a core dependency, but guard the import so the module stays
# importable (and the watcher degrades to periodic rescan) if it is missing.
try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:  # pragma: no cover - watchdog is a core dependency
    FileSystemEventHandler = object  # type: ignore[assignment, misc]
    Observer = None  # type: ignore[assignment]


def _load_state(path: Path) -> WatchState:
    return load_watch_state(path)


def _save_state(state: WatchState, path: Path) -> None:
    save_watch_state(state, path)


class _JsonlWatchHandler(FileSystemEventHandler):
    """Filesystem handler that records changed transcript paths, debounced.

    On every relevant event it stamps the path's last-event time (and whether
    the event implies the file is "new", e.g. created/moved) and pings a wake
    queue so the main loop can drain it. No I/O or DB work happens here — this
    runs on the watchdog observer thread, and we must not touch the sqlite
    connection from it.
    """

    def __init__(self, parser, wake_queue: "queue.Queue", debounce: float = 0.5):
        self._parser = parser
        self._queue = wake_queue
        self._debounce = debounce
        # path -> (last_event_time, reset_offset_flag)
        self._pending: dict[Path, tuple[float, bool]] = {}
        self._lock = threading.Lock()

    @property
    def parser(self):
        return self._parser

    @property
    def debounce(self) -> float:
        return self._debounce

    @staticmethod
    def _interested(path: str) -> bool:
        name = Path(path).name
        return (
            name.endswith(".jsonl")
            and not name.startswith("agent-")
            and "warmup" not in name.lower()
        )

    def _mark(self, path_str: str, reset: bool) -> None:
        if not self._interested(path_str):
            return
        path = Path(path_str)
        with self._lock:
            prev_time, prev_reset = self._pending.get(path, (0.0, False))
            # A created/moved event means the path is "new" — force a full
            # re-parse (a deleted-then-recreated file can reuse a stale offset).
            self._pending[path] = (time.monotonic(), prev_reset or reset)
        with contextlib.suppress(Exception):
            self._queue.put_nowait(None)  # wake the main loop

    def on_created(self, event) -> None:
        if not event.is_directory:
            self._mark(event.src_path, reset=True)

    def on_modified(self, event) -> None:
        if not event.is_directory:
            self._mark(event.src_path, reset=False)

    def on_moved(self, event) -> None:
        if not event.is_directory:
            self._mark(event.dest_path, reset=True)


class Watcher:
    """Event-driven file watcher for AI coding tool JSONL transcripts.

    On start it performs one initial full scan (``_poll``) so already-existing
    transcripts are indexed immediately, then installs a ``watchdog`` observer
    on each parser's ``watch_root()``. Changed files are synced on the main
    thread via a debounced drain loop.

    Adding a new AI tool source only requires registering a new Parser with a
    ``watch_root()`` — no watcher changes.

    Offsets are persisted to ``state.json`` (mirroring the scanner) so a crash
    or restart resumes incrementally instead of re-parsing every file from
    byte 0.
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
        # Resume from persisted offsets; live updates happen in ``_poll`` /
        # the event drain loop.
        self._state = _load_state(self._state_path)
        self._offsets: dict[str, int] = self._state.sessions
        self._failed: set[tuple[str, str]] = set()
        self._running = False
        self._closed = False
        self._last_save = 0.0
        self._save_interval = save_interval

        # Event-driven plumbing (wired up in ``watch``).
        self._wake: queue.Queue = queue.Queue()
        self._handlers: list[_JsonlWatchHandler] = []
        self._observer = None
        # Why the observer is (or isn't) active: one of
        # "uninitialized" | "ok" | "no_watchdog" | "no_roots" | "start_failed".
        # Drives the user-visible status + the hard-fail-on-missing-watchdog path.
        self._observer_state: str = "uninitialized"

    # -- public driver -------------------------------------------------

    def watch(
        self,
        interval: float = 0.25,
        *,
        debounce: float = 0.5,
        rescan_interval: float = 60.0,
    ) -> None:
        """Start watching. Runs until stopped via SIGINT/SIGTERM or Ctrl+C.

        Args:
            interval: Main-loop wake tick in seconds (how often we check for
                due files and persist offsets). Not a poll-scan interval — file
                changes are detected by the OS, not by polling.
            debounce: Coalesce events for the same file that arrive within this
                many seconds (a live session appends many times in a burst).
            rescan_interval: Periodic full re-scan safety net (seconds). Catches
                events watchdog can miss (atomic editor saves, network mounts).
                Set to 0 to disable. Default 60s — conservative enough that a
                missed event lags at most a minute, while still cutting scan
                frequency ~300x vs the old 1s poll.
        """
        self._running = True
        loop_interval = interval if interval and interval > 0 else 0.25

        # signal.signal only works in the main thread; guard for tests that run
        # watch() in a worker thread.
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, self._on_stop)
            signal.signal(signal.SIGTERM, self._on_stop)

        try:
            # One-time catch-up so existing transcripts are indexed at once.
            self._poll()
            self._install_observer(debounce=debounce)
            self._report_observer_state()

            # Hard fail: without watchdog the command cannot do its job, so we
            # must not silently degrade to a slow re-scan poll.
            if self._observer_state == "no_watchdog":
                self._running = False
                raise SystemExit(2)

            names = ", ".join(p.source_name for p in self._sources) or "(no parsers registered)"
            if self._observer_state == "ok":
                mode = "event-driven"
            else:
                mode = "re-scan safety-net (observer inactive)"
            print(f"Watching {names} transcripts ({mode}) ...")
            print("Press Ctrl+C to stop\n")

            self._event_loop(loop_interval, rescan_interval)
        finally:
            # Always stop the observer, persist offsets, and release the exporter
            # file handle — even when interrupted.
            self._stop_observer()
            self._persist_offsets()
            self.close()
            print("\nWatcher stopped.")

    # -- observer wiring -------------------------------------------------

    def _install_observer(self, debounce: float) -> None:
        if Observer is None:
            # Hard failure: the entire purpose of `watch` is event-driven sync.
            logger.error(
                "watchdog is not installed; cannot watch transcripts incrementally. "
                "Install it with: pip install bagger (watchdog is a core dependency)."
            )
            self._observer_state = "no_watchdog"
            return

        roots: list[tuple[object, Path]] = []
        for parser in self._sources:
            root = parser.watch_root()
            if root is None:
                logger.warning(
                    "Parser %s has no watch_root(); relying on periodic rescan only",
                    parser.source_name,
                )
                continue
            roots.append((parser, Path(root)))

        if not roots:
            # By design: every parser declined to be watched (watch_root() is
            # None). The rescan safety-net is the only sync path; not an error.
            logger.info("No watchable roots; relying on periodic rescan only")
            self._observer_state = "no_roots"
            return

        observer = Observer()
        started = False
        for parser, root in roots:
            if not root.exists():
                logger.warning("Watch root does not exist (skipping): %s", root)
                continue
            handler = _JsonlWatchHandler(parser, self._wake, debounce=debounce)
            try:
                observer.schedule(handler, str(root), recursive=True)
                self._handlers.append(handler)
            except Exception:
                logger.warning("Failed to schedule watch on %s", root, exc_info=True)

        if self._handlers:
            try:
                observer.start()
                started = True
            except Exception:
                logger.warning("Failed to start filesystem observer", exc_info=True)

        if started:
            self._observer = observer
            self._observer_state = "ok"
            return

        # Watchdog is present but no root could actually be watched (e.g. all
        # watch roots are missing, or scheduling/start raised). Degrade
        # gracefully to the rescan safety-net rather than crashing.
        logger.error(
            "Filesystem observer could not be started; the watcher will rely on "
            "the periodic re-scan safety-net (changed files may be delayed up to "
            "the re-scan interval). Check filesystem permissions and inotify/watch "
            "limits."
        )
        self._observer_state = "start_failed"
        with contextlib.suppress(Exception):
            observer.stop()

    def _report_observer_state(self) -> None:
        """Print a clear, user-visible status line about the active watch mode.

        The default ``logger`` output can be swallowed by CLI logging config, so
        the important failure modes are printed to stderr directly — we must
        never *silently* degrade to the slow re-scan poll.
        """
        if self._observer_state == "no_watchdog":
            print(
                "✗ watchdog is NOT installed — `watch` cannot run in event-driven "
                "mode. Install it with: pip install bagger  (watchdog is a core "
                "dependency). Exiting.",
                file=sys.stderr,
            )
        elif self._observer_state == "start_failed":
            print(
                "! WARNING: filesystem observer failed to start. The watcher is "
                "falling back to the periodic re-scan safety-net only — changed "
                "files may not sync for up to the re-scan interval. Check "
                "filesystem permissions / inotify (Linux) or watch limits.",
                file=sys.stderr,
            )
        elif self._observer_state == "no_roots":
            print(
                "ℹ No watchable roots reported by any parser; using the periodic "
                "re-scan safety-net only.",
                file=sys.stderr,
            )

    def _stop_observer(self) -> None:
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=5)
            except Exception:
                logger.warning("Error stopping observer", exc_info=True)
            self._observer = None

    # -- main event loop -------------------------------------------------

    def _event_loop(self, loop_interval: float, rescan_interval: float) -> None:
        last_rescan = time.monotonic()
        while self._running:
            with contextlib.suppress(queue.Empty):
                self._wake.get(timeout=loop_interval)

            self._drain_pending()
            self._maybe_persist_offsets()

            if rescan_interval and rescan_interval > 0:
                now = time.monotonic()
                if now - last_rescan >= rescan_interval:
                    self._poll()  # safety-net full re-scan
                    last_rescan = now

    def _drain_pending(self) -> int:
        """Sync every pending file whose debounce window has elapsed.

        Called from the main thread only. Pops due entries under each handler's
        lock, then performs the (potentially slow) sync outside the lock.
        Returns the number of files synced.
        """
        due: list[tuple[Path, str, bool]] = []
        now = time.monotonic()
        for handler in self._handlers:
            with handler._lock:
                ready = [
                    p
                    for p, (ts, _reset) in handler._pending.items()
                    if now - ts >= handler.debounce
                ]
                for p in ready:
                    _ts, reset = handler._pending.pop(p)
                    due.append((p, handler.parser.source_name, reset))

        for path, source_name, reset in due:
            self._sync_path(path, source_name, reset=reset)
        return len(due)

    # -- per-file sync (shared by initial scan + events) -----------------

    def _sync_path(self, filepath: Path, source_name: str, reset: bool = False) -> None:
        """Sync a single transcript file, recording failures.

        ``reset`` forces the offset back to 0 (used for created/moved events,
        where a stale offset would otherwise skip a genuinely new file). Also
        auto-resets when a file has shrunk (truncation / log rotation).
        """
        sync = self._syncs[source_name]
        # The offset/failure key MUST match SyncService.sync_file exactly: the
        # parser owns the filename→session-id mapping (Claude: stem is the id;
        # Codex: the id lives in session_meta, not the filename). Keying on
        # filepath.stem here would track the wrong offset for Codex and silently
        # disable the shrink/created detection below for that source.
        session_id = sync.parser.session_id_for(filepath)
        if (source_name, session_id) in self._failed:
            return  # already logged a parse error this run; avoid spam

        offset_key = f"{source_name}:{session_id}"
        legacy_key = session_id
        if reset:
            self._offsets.pop(offset_key, None)
            self._offsets.pop(legacy_key, None)
        elif filepath.exists():
            try:
                size = filepath.stat().st_size
            except OSError:
                size = 0
            if size < self._offsets.get(offset_key, 0):
                # File shrank since we last read it (truncated / rotated): the
                # stored offset is now past EOF, so re-parse from the start.
                self._offsets.pop(offset_key, None)
                self._offsets.pop(legacy_key, None)

        try:
            result = sync.sync_file(filepath, self._offsets, upsert_always=False)
        except SyncError as exc:
            self._failed.add((source_name, session_id))
            logger.error(
                "Parse failed for %s — skipping for the rest of this run. "
                "Fix the file and restart the watcher to retry.",
                exc.filepath,
            )
            return

        if result.skipped:
            return

        # Only report when new events were inserted.
        if result.new_count > 0:
            if result.is_first_sight:
                summary = sync.parser.extract_summary(filepath)
                print(f'  [new] session {filepath.stem[:8]} "{summary}"')
            print(f"    +{result.new_count} events synced")

    def _poll(self) -> None:
        """Initial / periodic full scan: discover and sync every session file.

        This is the event-driven watcher's bootstrap (run once at startup) and
        its periodic safety-net rescan — not a per-second poll.
        """
        for source_name, sync in self._syncs.items():
            parser = sync.parser
            files = parser.discover_sessions()
            for filepath in files:
                self._sync_path(filepath, source_name, reset=False)

    # -- offset persistence --------------------------------------------

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

    # -- lifecycle ------------------------------------------------------

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

    def _on_stop(self, signum, frame):
        self._running = False
        del signum, frame
