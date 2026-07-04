"""Real-time watcher: poll for new JSONL lines and sync incrementally."""

import signal
import time
from pathlib import Path

from bagger.exporters.jsonl import JsonlExporter
from bagger.parser.claude import extract_summary
from bagger.services.scanner import discover_sessions, upsert_session_from_events
from bagger.storage.sqlite import SqliteStorage


class Watcher:
    """Polling-based file watcher for Claude Code JSONL transcripts."""

    def __init__(self, storage: SqliteStorage, projects_dir: Path | None = None):
        self.storage = storage
        self.projects_dir = projects_dir
        self._offsets: dict[str, int] = {}
        self._running = False
        self._exporter = JsonlExporter(Path.home() / ".bagger" / "events.jsonl")

    def watch(self, interval: float = 1.0) -> None:
        """Start watching. Runs until Ctrl+C."""
        self._running = True

        signal.signal(signal.SIGINT, self._on_stop)
        signal.signal(signal.SIGTERM, self._on_stop)

        print(f"Watching {self.projects_dir or '~/.claude/projects/'} ...")
        print("Press Ctrl+C to stop\n")

        while self._running:
            try:
                self._poll()
                time.sleep(interval)
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"  [!] Watch error: {e}")

        print("\nWatcher stopped.")

    def _poll(self) -> None:
        files = discover_sessions(self.projects_dir)
        for filepath in files:
            session_id = filepath.stem
            file_size = filepath.stat().st_size
            last_offset = self._offsets.get(session_id, 0)

            if file_size <= last_offset:
                continue

            from bagger.services.scanner import _parse_new_lines

            try:
                new_events = _parse_new_lines(filepath, last_offset)
            except Exception:
                continue

            if not new_events:
                continue

            count = self.storage.insert_events(new_events)
            self._export(new_events)

            if count > 0:
                upsert_session_from_events(
                    self.storage,
                    session_id,
                    filepath,
                    new_events,
                )
                if last_offset == 0:
                    summary = extract_summary(filepath)
                    print(f'  [new] session {session_id[:8]} "{summary}"')
                print(f"    +{count} events synced")

            self._offsets[session_id] = file_size

    def _on_stop(self, signum, frame):
        self._running = False

    def _export(self, events: list) -> None:
        for ev in events:
            try:
                self._exporter.export_event(ev)
            except Exception:
                pass
