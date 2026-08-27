"""Shared text-normalization primitives.

A leaf module, in the same spirit as ``bagger.cjk``: pure functions with no
project dependencies, so the storage layer (schema migrations that backfill
content hashes) can import them without creating a cycle or a reverse
dependency.

The layering rule in CONTRIBUTING.md is ``cli/api -> services -> parsers/storage
-> models``. Putting the hash function here is what makes migration v6 able to
backfill fingerprints while keeping exactly one definition of "what counts as
the same content".
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Iterable

__all__ = [
    "char_bigrams",
    "content_fingerprint",
    "jaccard",
    "normalize_content",
]

# Unicode general-category initials that carry no semantic weight for
# duplicate detection: P=punctuation, S=symbol/emoji, Z=separator,
# C=control/format. Letters (L), numbers (N) and combining marks (M) survive.
_DROPPED_CATEGORIES = frozenset("PSZC")


def normalize_content(text: str) -> str:
    """Reduce ``text`` to a comparison skeleton.

    NFKC-folds compatibility forms (full-width "Ｚｖｅｃ" -> "Zvec"), casefolds,
    then drops every whitespace, punctuation and symbol character. The result is
    not human-readable and is never persisted as content — it exists only to be
    hashed or sliced into bigrams.

    >>> normalize_content("使用 `HashRouter`，而非 BrowserRouter！")
    '使用hashrouter而非browserrouter'
    """
    if not text:
        return ""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return "".join(ch for ch in folded if unicodedata.category(ch)[0] not in _DROPPED_CATEGORIES)


def content_fingerprint(record_type: str, content: str) -> str:
    """Stable 16-hex-char fingerprint of ``(record_type, normalized content)``.

    Scoping by type is deliberate: "用 Zvec 替代 Chroma" recorded as a
    ``decision`` and as a ``fact`` are different cognitive units and must not
    swallow each other.

    Truncated SHA-1 rather than the full digest: 64 bits is ample for a corpus
    that would need billions of records before a birthday collision becomes
    likely, and short hashes keep the index small and debug output readable.
    This is a dedup key, not a security primitive.
    """
    skeleton = normalize_content(content)
    payload = f"{record_type}\x00{skeleton}".encode()
    return hashlib.sha1(payload, usedforsecurity=False).hexdigest()[:16]


def char_bigrams(text: str, *, already_normalized: bool = False) -> frozenset[str]:
    """Character bigram set of ``text``.

    Character bigrams rather than word tokens because the corpus is
    predominantly Chinese, where whitespace carries no word boundary. Bigrams
    are language-agnostic, need no segmentation dependency, and behave sanely
    on the mixed CJK/ASCII text that AI-coding transcripts produce.

    Strings shorter than two characters degrade to a single unigram so that very
    short records still participate in comparison instead of producing an empty
    set (whose Jaccard against anything is undefined).
    """
    skeleton = text if already_normalized else normalize_content(text)
    if len(skeleton) < 2:
        return frozenset([skeleton]) if skeleton else frozenset()
    return frozenset(skeleton[i : i + 2] for i in range(len(skeleton) - 1))


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    """Jaccard similarity of two bigram sets. Returns 0.0 if either is empty."""
    sa, sb = frozenset(a), frozenset(b)
    if not sa or not sb:
        return 0.0
    union = len(sa | sb)
    return len(sa & sb) / union if union else 0.0
