"""JSONL exporter: append raw events to a JSONL file for backup."""

import json
from pathlib import Path

from bagger.exporters.base import Exporter
from bagger.models.event import MemoryEvent


class JsonlExporter(Exporter):
    """Append each MemoryEvent as one JSON line to a file.

    Keeps the file handle open for efficient sequential writes.
    Call flush() to persist, close explicitly or let GC handle it.
    """

    def __init__(self, path: Path):
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = None

    def _ensure_open(self):
        if self._file is None:
            self._file = open(self._path, "a", encoding="utf-8")

    def export_event(self, event: MemoryEvent) -> None:
        self._ensure_open()
        self._file.write(event.model_dump_json() + "\n")

    def flush(self) -> None:
        if self._file:
            self._file.flush()
