"""Parser package — abstract protocol + concrete implementations.

Auto-registers ClaudeParser on import so scanner/watcher can discover it.
"""

from bagger.parser.base import Parser, ParserRegistry

from bagger.parser.claude import ClaudeParser

# ── Auto-register known parsers ──

try:
    ParserRegistry.register(ClaudeParser())
except Exception:
    pass  # non-fatal: Parser can be registered manually later

__all__ = [
    "Parser",
    "ParserRegistry",
    "ClaudeParser",
]
