"""Real-time watcher: poll for new JSONL lines and sync incrementally.

The per-file sync pipeline (discover → parse → insert → export → upsert
→ advance offset) lives in ``bagger.services.sync.SyncService``. This
module is the polling driver: it discovers session files and delegates
each file to ``SyncService``.
"""

import signal
import time

from bagger.parser import ParserRegistry
from bagger.services.sync import SyncService
from bagger.storage.base import Storage


class Watcher:
    """Polling-based file watcher for AI coding tool JSONL transcripts.

    Each poll cycle discovers session files via ``ParserRegistry`` and
    delegates per-file syncing to ``SyncService``.  Adding a new AI tool
    source only requires registering a new Parser — no watcher changes.
    """

    def __init__(
        self,
        storage: Storage,
        source: str = "claude",
    ):
        self.storage = storage
        self.parser = ParserRegistry.get(source)
        self._sync = SyncService(storage, self.parser)
        self._offsets: dict[str, int] = {}
        self._running = False

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
        files = self.parser.discover_sessions()

        for filepath in files:
            result = self._sync.sync_file(filepath, self._offsets, upsert_always=False)
            if result is None:
                continue  # parse error swallowed
            if result.skipped:
                continue

            # Only report when new events were inserted (watcher prints).
            if result.new_count > 0:
                if result.is_first_sight:
                    summary = self.parser.extract_summary(filepath)
                    session_id = filepath.stem
                    print(f'  [new] session {session_id[:8]} "{summary}"')
                print(f"    +{result.new_count} events synced")

    def _on_stop(self, signum, frame):
        self._running = False
        del signum, frame
