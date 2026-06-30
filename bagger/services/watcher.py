"""Real-time watcher: poll for new JSONL lines and sync incrementally."""

import signal
import time
from pathlib import Path
from typing import Optional

from bagger.exporters.jsonl import JsonlExporter
from bagger.services.scanner import discover_sessions, _read_from_offset
from bagger.storage.sqlite import SqliteStorage


class Watcher:
    """Polling-based file watcher for Claude Code JSONL transcripts."""

    def __init__(self, storage: SqliteStorage, projects_dir: Optional[Path] = None):
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

            try:
                new_events = _read_from_offset(filepath, last_offset)
            except Exception:
                continue

            if not new_events:
                continue

            count = self.storage.insert_events(new_events)
            self._export(new_events)

            from bagger.parser.claude import extract_summary
            from bagger.models.event import Session

            summary = extract_summary(filepath)
            if count > 0:
                existing = self.storage.get_event_count(session_id)
                project_path = (
                    new_events[0].cwd or ""
                    if new_events
                    else ""
                )
                first_ts = new_events[0].timestamp if new_events else None
                last_ts = new_events[-1].timestamp if new_events else None

                session = Session(
                    session_id=session_id,
                    summary=summary,
                    project_path=project_path,
                    message_count=existing,
                    first_message_at=first_ts,
                    last_message_at=last_ts,
                )
                self.storage.upsert_session(session)

                if last_offset == 0:
                    print(f"  [new] session {session_id[:8]} \"{summary}\"")
                print(f"    +{count} events synced")

            self._offsets[session_id] = file_size

    def _on_stop(self, signum, frame):
        self._running = False

    def _export(self, events: list) -> None:
        """Export events to JSONL backup, ignoring errors."""
        for ev in events:
            try:
                self._exporter.export_event(ev)
            except Exception:
                pass
