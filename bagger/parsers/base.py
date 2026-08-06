"""Parser Protocol — every AI tool transcript source implements this."""

import importlib
import inspect
import logging
import pkgutil
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from bagger.models.event import MemoryEvent

logger = logging.getLogger(__name__)


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

    def watch_root(self) -> "Path | None":
        """Base directory to watch for transcript changes, or ``None`` if the
        source cannot be watched incrementally (e.g. discovery spans many
        unrelated roots).

        The watcher (``bagger.services.watcher``) uses this to install a
        filesystem observer on the correct directory instead of re-scanning
        every poll cycle. Concrete parsers that know their single base dir
        (Claude Code's ``~/.claude/projects``) override this; parsers whose
        discovery is ad-hoc return ``None`` and the watcher falls back to a
        periodic full re-scan.

        This is a concrete method (not abstract) so existing parsers keep
        working without changes.
        """
        return None

    def session_id_for(self, path: "Path") -> str:
        """Canonical session id for a transcript file.

        Default: the filename stem (true for Claude Code, whose transcripts
        are named ``<sessionId>.jsonl``). Sources whose filenames don't equal
        the session id — Codex's ``rollout-{ts}-{uuid}.jsonl`` — override this
        to read the id from the file's own metadata. SyncService keys the
        ``Session`` row and the watch offset on whatever this returns, so it
        must agree with the ``session_id`` stamped on parsed events.
        """
        return path.stem

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
    _loaded: bool = False

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
    def all_parsers(cls) -> list["Parser"]:
        """Return every registered parser instance.

        Used by the scanner/watcher to drive *all* sources (multi-tool
        support, §5.5) instead of a single hard-coded one.
        """
        return list(cls._parsers.values())

    @classmethod
    def discover_all(cls) -> dict[str, list[Path]]:
        """Run discover on every registered parser."""
        result: dict[str, list[Path]] = {}
        for name, parser in cls._parsers.items():
            result[name] = parser.discover_sessions()
        return result

    @classmethod
    def load_builtin(cls, force: bool = False) -> None:
        """Auto-register every concrete :class:`Parser` in the
        ``bagger.parsers`` package (see :func:`_iter_parser_classes`).

        Adding a new AI tool source is now just dropping a module in
        ``parsers/`` — no registry edits. Idempotent: scans once unless
        ``force=True``. A broken plugin logs a warning and is skipped so it
        can't block the rest from loading.
        """
        if cls._loaded and not force:
            return
        for klass in _iter_parser_classes():
            try:
                cls.register(klass())
            except Exception:
                logger.warning("Failed to register parser %s", klass.__name__, exc_info=True)
        cls._loaded = True

    @classmethod
    def clear(cls) -> None:
        """For testing only — reset the registry."""
        cls._parsers.clear()
        cls._loaded = False


def _iter_parser_classes() -> Iterator[type["Parser"]]:
    """Yield concrete :class:`Parser` subclasses defined in this package.

    Drives :meth:`ParserRegistry.load_builtin`: every module in
    ``bagger/parsers/`` that defines a non-abstract ``Parser`` subclass gets
    picked up — so new sources register automatically on import. Modules
    whose name starts with ``_`` (helpers like ``_common``) and the protocol
    module (``base``) are skipped; only classes *defined* in a plugin module
    are yielded, so a parser imported merely for type hints isn't double
    registered.
    """
    import bagger.parsers as _pkg

    for mod_info in pkgutil.iter_modules(_pkg.__path__, prefix="bagger.parsers."):
        module_name = mod_info.name
        basename = module_name.rsplit(".", 1)[-1]
        if basename.startswith("_") or basename in {"base"}:
            continue
        try:
            module = importlib.import_module(module_name)
        except Exception:
            logger.warning("Skipping unimportable parser module %s", module_name, exc_info=True)
            continue
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, Parser)
                and obj is not Parser
                and not inspect.isabstract(obj)
                and obj.__module__ == module.__name__
            ):
                yield obj
