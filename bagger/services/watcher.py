"""Real-time watcher: poll for new JSONL lines and sync incrementally."""

import contextlib
import signal
import time
from pathlib import Path

from bagger.exporters.jsonl import JsonlExporter
from bagger.parser import ParserRegistry
from bagger.services.scanner import upsert_session_from_events
from bagger.storage.sqlite import SqliteStorage


class Watcher:
    """Polling-based file watcher for AI coding tool JSONL transcripts.

    Obtains the parser from ParserRegistry by source name so adding
    a new tool only requires registering a new Parser --- no watcher changes.
    """

    def __init__(
        self,
        storage: SqliteStorage,
        source: str = "claude",
    ):
        self.storage = storage
        self.parser = ParserRegistry.get(source)
        self._offsets: dict[str, int] = {}
        self._running = False
        self._exporter = JsonlExporter(Path.home() / ".bagger" / "events.jsonl")

    def watch(self, interval: float = 1.0) -> None:
        """Start watching. Runs until Ctrl+C."""
        self._running = True

        signal.signal(signal.SIGINT, self._on_stop)
        signal.signal(signal.SIGTERM, self._on_stop)

        print(f"Watching {self.parser.source_name} transcripts ...")
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
        parser = self.parser
        files = parser.discover_sessions()

        for filepath in files:
            session_id = filepath.stem
            file_size = filepath.stat().st_size
            last_offset = self._offsets.get(session_id, 0)

            if file_size <= last_offset:
                continue

            try:
                new_events = parser.parse_incremental(filepath, last_offset)
            except Exception:
                continue

            if not new_events:
                continue

            count = self.storage.insert_events(new_events)
            self._export(new_events)

            if count > 0:
                upsert_session_from_events(
                    self.storage, parser, session_id, filepath, new_events,
                )
                if last_offset == 0:
                    summary = parser.extract_summary(filepath)
                    print(f'  [new] session {session_id[:8]} "{summary}"')
                print(f"    +{count} events synced")

            self._offsets[session_id] = file_size

    def _on_stop(self, signum, frame):
        self._running = False

    def _export(self, events: list) -> None:
        for ev in events:
            with contextlib.suppress(Exception):
                self._exporter.export_event(ev)
