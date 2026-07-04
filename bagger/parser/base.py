"""Parser Protocol — every AI tool transcript source implements this."""

from abc import ABC, abstractmethod
from pathlib import Path

from bagger.models.event import MemoryEvent


class Parser(ABC):
    """Abstract parser for AI coding tool transcripts.

    Each concrete parser handles one tool (Claude Code, Cursor, etc.).
    Scanner and watcher depend on this interface, not on specific parsers.
    """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Unique identifier, e.g. 'claude', 'cursor'."""
        ...

    @abstractmethod
    def discover_sessions(self) -> list[Path]:
        """Find all session transcript files for this source."""
        ...

    @abstractmethod
    def parse(self, path: Path) -> list[MemoryEvent]:
        """Parse a full transcript file into MemoryEvent objects."""
        ...

    @abstractmethod
    def parse_incremental(self, path: Path, offset: int) -> list[MemoryEvent]:
        """Parse only new lines appended after the given byte offset."""
        ...

    @abstractmethod
    def extract_summary(self, path: Path) -> str:
        """Extract a human-readable summary from the transcript file."""
        ...


class ParserRegistry:
    """Global registry of known parsers, keyed by source_name."""

    _parsers: dict[str, Parser] = {}

    @classmethod
    def register(cls, parser: Parser) -> None:
        if not parser.source_name:
            raise ValueError("Parser must have a non-empty source_name")
        cls._parsers[parser.source_name] = parser

    @classmethod
    def get(cls, source_name: str) -> Parser:
        parser = cls._parsers.get(source_name)
        if parser is None:
            available = ", ".join(sorted(cls._parsers))
            raise KeyError(
                f"Unknown parser source: '{source_name}'. "
                f"Available: {available or '(none registered)'}"
            )
        return parser

    @classmethod
    def list_all(cls) -> list[str]:
        return sorted(cls._parsers)

    @classmethod
    def discover_all(cls) -> dict[str, list[Path]]:
        """Run discover on every registered parser."""
        result: dict[str, list[Path]] = {}
        for name, parser in cls._parsers.items():
            result[name] = parser.discover_sessions()
        return result

    @classmethod
    def clear(cls) -> None:
        """For testing only — reset the registry."""
        cls._parsers.clear()
