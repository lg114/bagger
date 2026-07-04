"""Parser package — abstract protocol + concrete implementations.

Auto-registers ClaudeParser on import so scanner/watcher can discover it.
"""

import contextlib

from bagger.parser.base import Parser, ParserRegistry
from bagger.parser.claude import ClaudeParser

# ── Auto-register known parsers ──

with contextlib.suppress(Exception):
    ParserRegistry.register(ClaudeParser())

__all__ = [
    "Parser",
    "ParserRegistry",
    "ClaudeParser",
]
