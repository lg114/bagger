"""Parser Protocol — every AI tool transcript source implements this."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from bagger.models.event import MemoryEvent


@dataclass
class StandardUsage:
    """Provider-agnostic normalized usage — the target of parser normalization.

    Each concrete parser maps its provider-specific usage dict into this shape
    so the rest of bagger only ever deals with one schema. ``cost_usd`` is
    *stored* when the transcript provides it (Anthropic backends); bagger never
    computes it.
    """

    token_input: int = 0
    token_output: int = 0
    token_cache_read: int = 0
    token_cache_write: int = 0
    cost_usd: float | None = None
    currency: str = "USD"
    service_tier: str | None = None


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

    @abstractmethod
    def normalize_usage(self, raw_usage: dict, raw_model: str | None = None) -> StandardUsage:
        """Normalize a provider's raw ``usage`` dict into :class:`StandardUsage`.

        Concrete parsers map provider-specific token/cache/cost fields here.
        This is the seam that lets bagger support non-Anthropic backends whose
        usage schemas differ (e.g. OpenAI-compatible ``prompt_tokens``).
        """
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
