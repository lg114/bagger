"""JSONL exporter: append raw events to a JSONL file for backup."""

import json
from pathlib import Path

from bagger.exporters.base import Exporter
from bagger.models.event import MemoryEvent


class JsonlExporter(Exporter):
    """Append each MemoryEvent as one JSON line to a file."""

    def __init__(self, path: Path):
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def export_event(self, event: MemoryEvent) -> None:
        line = event.model_dump_json()
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def flush(self) -> None:
        pass  # aopen with "a" flushes immediately
