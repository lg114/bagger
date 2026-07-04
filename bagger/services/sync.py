"""SyncService — the single source of truth for the per-file sync pipeline.

Both `scanner.scan_all()` (batch import) and `watcher.Watcher._poll()` (tail
polling) do the same thing: for each transcript file, discover it, check its
byte offset, parse new lines, insert events, export a backup, upsert session
metadata, and advance the offset. That pipeline lives here once.

Differences between the two callers (offset persistence, upsert gating, parse
method on first sight) are expressed as parameters, not branches inside the
service, so each caller replicates its current behavior exactly.
"""

import contextlib
from dataclasses import dataclass
from pathlib import Path

from bagger.exporters.jsonl import JsonlExporter
from bagger.models.event import MemoryEvent, Session
from bagger.parser.base import Parser
from bagger.storage.base import SessionRepository, Storage


def upsert_session_from_events(
    storage: SessionRepository,
    parser: Parser,
    session_id: str,
    filepath: Path,
    events: list[MemoryEvent],
) -> None:
    """Upsert session metadata derived from a list of parsed events."""
    summary = parser.extract_summary(filepath)
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


@dataclass
class SyncResult:
    """Outcome of syncing a single transcript file."""

    new_count: int
    """Number of newly inserted events (return value of ``insert_events``)."""

    skipped: bool
    """True if the file was unchanged since the last offset (nothing to do)."""

    is_first_sight: bool
    """True if the offset was 0 before this sync (watcher uses this to print "[new]")."""

    advanced_offset: bool
    """True if the offset was advanced to ``file_size`` after a successful sync."""


class SyncService:
    """Per-file sync pipeline shared by scanner (batch) and watcher (poll)."""

    def __init__(
        self,
        storage: Storage,
        parser: Parser,
        jsonl_path: Path | None = None,
    ):
        self.storage = storage
        self.parser = parser
        self._exporter = JsonlExporter(jsonl_path or Path.home() / ".bagger" / "events.jsonl")

    def close(self) -> None:
        """Flush and close the exporter file handle. Safe to call multiple times."""
        self._exporter.close()

    def sync_file(
        self,
        filepath: Path,
        offsets: dict[str, int],
        *,
        full: bool = False,
        upsert_always: bool = True,
    ) -> SyncResult | None:
        """Sync a single transcript file, advancing ``offsets`` in place.

        Args:
            filepath: Path to the JSONL transcript.
            offsets: Mutable offset map (``session_id -> byte offset``). Mutated
                in place when events are synced. The caller owns persistence
                (scanner persists via ``WatchState`` JSON; watcher keeps it in memory).
            full: If True, ignore the existing offset and re-parse from scratch.
                Also forces ``parse()`` instead of ``parse_incremental()``.
            upsert_always: If True, upsert session metadata even when no new
                events were inserted (scanner's behavior). If False, only upsert
                when ``new_count > 0`` (watcher's behavior).

        Returns:
            ``SyncResult`` describing what happened, or ``None`` if a parse
            error was swallowed (matching the prior silent-continue behavior).
        """
        session_id = filepath.stem
        file_size = filepath.stat().st_size
        last_offset = offsets.get(session_id, 0)
        is_first_sight = last_offset == 0

        # Skip unchanged files (scanner suppresses this check in full mode;
        # watcher never passes full=True).
        if not full and last_offset >= file_size:
            return SyncResult(
                new_count=0,
                skipped=True,
                is_first_sight=is_first_sight,
                advanced_offset=False,
            )

        try:
            events = (
                self.parser.parse(filepath)
                if is_first_sight or full
                else self.parser.parse_incremental(filepath, last_offset)
            )
        except Exception:
            return None

        if not events:
            return SyncResult(
                new_count=0,
                skipped=False,
                is_first_sight=is_first_sight,
                advanced_offset=False,
            )

        new_count = self.storage.insert_events(events)
        self._export_events(events)

        if upsert_always or new_count > 0:
            upsert_session_from_events(self.storage, self.parser, session_id, filepath, events)

        offsets[session_id] = file_size
        return SyncResult(
            new_count=new_count,
            skipped=False,
            is_first_sight=is_first_sight,
            advanced_offset=True,
        )

    def _export_events(self, events: list[MemoryEvent]) -> None:
        """Export events to JSONL backup, ignoring per-event errors."""
        for ev in events:
            with contextlib.suppress(Exception):
                self._exporter.export_event(ev)
