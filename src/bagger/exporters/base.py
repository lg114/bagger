"""Exporter interface."""

from abc import ABC, abstractmethod

from bagger.models.event import MemoryEvent


class Exporter(ABC):
    """Abstract base for all exporters (JSONL, SQLite, Zvec, etc.)."""

    @abstractmethod
    def export_event(self, event: MemoryEvent) -> None: ...

    @abstractmethod
    def flush(self) -> None: ...
