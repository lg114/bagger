"""Parser package — abstract protocol + concrete implementations.

On import, :meth:`ParserRegistry.load_builtin` scans this package and
auto-registers every concrete ``Parser`` subclass, so adding a new AI tool
source is just a matter of dropping a module in here (no registry edits).
"""

from bagger.parsers.base import Parser, ParserRegistry

# Auto-register all concrete parsers found in this package.
ParserRegistry.load_builtin()

__all__ = [
    "Parser",
    "ParserRegistry",
]
