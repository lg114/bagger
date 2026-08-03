"""Parser package — abstract protocol + concrete implementations.

Auto-registers known parsers on import so scanner/watcher can discover them.
"""

import logging

from bagger.parsers.base import Parser, ParserRegistry
from bagger.parsers.claude import ClaudeParser
from bagger.parsers.codex import CodexParser

logger = logging.getLogger(__name__)

# ── Auto-register known parsers ──

for _parser in (ClaudeParser(), CodexParser()):
    try:
        ParserRegistry.register(_parser)
    except Exception:
        # A broken parser must fail loudly, not hide behind suppress() and then
        # blow up later with a cryptic KeyError from ParserRegistry.get().
        logger.warning("Failed to auto-register %s", type(_parser).__name__, exc_info=True)

__all__ = [
    "Parser",
    "ParserRegistry",
    "ClaudeParser",
    "CodexParser",
]
