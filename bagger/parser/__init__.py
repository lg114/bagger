"""Parser package — abstract protocol + concrete implementations.

Auto-registers ClaudeParser on import so scanner/watcher can discover it.
"""

import logging

from bagger.parser.base import Parser, ParserRegistry
from bagger.parser.claude import ClaudeParser

logger = logging.getLogger(__name__)

# ── Auto-register known parsers ──

try:
    ParserRegistry.register(ClaudeParser())
except Exception:
    # A broken parser must fail loudly, not hide behind suppress() and then
    # blow up later with a cryptic KeyError from ParserRegistry.get().
    logger.warning("Failed to auto-register ClaudeParser", exc_info=True)

__all__ = [
    "Parser",
    "ParserRegistry",
    "ClaudeParser",
]
