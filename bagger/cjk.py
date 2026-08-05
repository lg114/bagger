"""Shared CJK / jieba detection helpers.

Extracted from ``bagger.storage.sqlite`` so that non-storage layers (scanner,
CLI) can use the jieba guard without reaching into storage-private symbols.
``storage/sqlite`` and ``services/scanner`` both import these public names
directly; this module is the single source of truth.
"""

import re

_CJK_RE = re.compile(
    r"["
    r"\u4e00-\u9fff"  # CJK Unified Ideographs
    r"\u3400-\u4dbf"  # CJK Unified Extension A
    r"\uf900-\ufaff"  # CJK Compatibility
    r"\u3040-\u309f"  # Hiragana
    r"\u30a0-\u30ff"  # Katakana
    r"\uac00-\ud7af"  # Hangul
    r"]"
)

# Surfaced (non-fatally) when CJK search would be silently broken: FTS5's
# unicode61 tokenizer does NOT split Chinese/Japanese/Korean characters, so
# without jieba pre-tokenization the text is indexed as one opaque blob and
# CJK queries return nothing. This is the exact failure we hit when a source
# was scanned in an environment lacking jieba.
JIEBA_CJK_WARNING = (
    "jieba is not installed — Chinese/Japanese/Korean text will be indexed as "
    "opaque blobs and CJK search queries will return NO results. "
    "Fix: `pip install jieba`, then re-run this command "
    "(or `bagger rebuild-index` to re-index already-imported data)."
)

_jieba_cached: bool | None = None  # tri-state: None=not checked, True/False=result


def jieba_available() -> bool:
    """True if jieba is importable (cached after first check)."""
    global _jieba_cached
    if _jieba_cached is None:
        try:
            import jieba  # noqa: F401

            _jieba_cached = True
        except ImportError:
            _jieba_cached = False
    return _jieba_cached


def contains_cjk(text: str) -> bool:
    """Return True if ``text`` contains any CJK / Kana / Hangul codepoint."""
    return bool(_CJK_RE.search(text))
