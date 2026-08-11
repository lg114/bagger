"""Near-duplicate detection over distilled memory records.

The pure text primitives (normalize / fingerprint / bigrams / Jaccard) live in
:mod:`bagger.textnorm` so the storage layer can reuse them without importing
consolidation. This module adds the consolidation-specific half: candidate
generation, thresholding and clustering.

Three layers of duplicate detection, in increasing cost and decreasing certainty:

1. :func:`~bagger.textnorm.normalize_content` — two records differing only in
   "，" vs "," or full-width vs half-width digits collapse to one skeleton.
2. :func:`~bagger.textnorm.content_fingerprint` — exact-duplicate detection
   becomes a dict lookup.
3. :func:`find_near_duplicate_pairs` — paraphrases that survive normalization
   ("Tauri 应用中应使用 HashRouter 而非 BrowserRouter" vs "Tauri webview 不支持
   History API，必须用 HashRouter") need a similarity scan.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

from bagger.textnorm import (
    char_bigrams,
    content_fingerprint,
    jaccard,
    normalize_content,
)

__all__ = [
    "DEFAULT_FUZZY_THRESHOLD",
    "NearDuplicatePair",
    "char_bigrams",
    "cluster_pairs",
    "content_fingerprint",
    "find_near_duplicate_pairs",
    "jaccard",
    "normalize_content",
]

# Measured against the live corpus (364 records, ~57 chars each): genuine
# paraphrase pairs cluster at Jaccard 0.55-0.72 while unrelated records sit
# below 0.45. 0.72 keeps the automatic suggestion set tight — fuzzy merging is
# lossy, so the default errs toward under-merging and leaves the rest to an
# explicit lower --threshold run that the operator previews first.
DEFAULT_FUZZY_THRESHOLD = 0.72


class NearDuplicatePair(NamedTuple):
    """Two record keys judged to be near-duplicates, with their similarity."""

    left: int
    right: int
    similarity: float


def find_near_duplicate_pairs(
    items: Sequence[tuple[int, str, str]],
    threshold: float = DEFAULT_FUZZY_THRESHOLD,
) -> list[NearDuplicatePair]:
    """Find near-duplicate pairs among ``items`` of ``(key, type, content)``.

    Only records sharing the same ``type`` are ever compared — a ``lesson`` and
    a ``fact`` phrased alike remain distinct units.

    A naive scan is O(n^2): fine at today's 364 records (66k comparisons,
    milliseconds), ruinous at 100k (5 billion). Two prunings keep it near-linear
    in practice:

    * **Inverted index** — only records sharing at least one bigram become
      candidates. Unrelated records are never compared at all.
    * **Length bound** — Jaccard is bounded above by
      ``min(|A|,|B|) / max(|A|,|B|)``, so a size ratio below ``threshold``
      makes the threshold unreachable and the pair is skipped before any set
      intersection is computed.

    Returns pairs sorted by descending similarity, so the caller can present
    the most confident merges first.
    """
    if not 0.0 < threshold <= 1.0:
        raise ValueError(f"threshold must be in (0, 1], got {threshold}")

    grams: dict[int, frozenset[str]] = {}
    types: dict[int, str] = {}
    for key, record_type, content in items:
        bigrams = char_bigrams(content)
        if bigrams:
            grams[key] = bigrams
            types[key] = record_type

    # (type, bigram) -> keys containing it, so cross-type pairs are never even
    # generated.
    postings: dict[tuple[str, str], list[int]] = {}
    for key, bigrams in grams.items():
        record_type = types[key]
        for gram in bigrams:
            postings.setdefault((record_type, gram), []).append(key)

    seen: set[tuple[int, int]] = set()
    pairs: list[NearDuplicatePair] = []
    for key, bigrams in grams.items():
        record_type = types[key]
        size = len(bigrams)
        candidates: set[int] = set()
        for gram in bigrams:
            candidates.update(postings.get((record_type, gram), ()))
        candidates.discard(key)

        for other in candidates:
            edge = (key, other) if key < other else (other, key)
            if edge in seen:
                continue
            seen.add(edge)
            other_grams = grams[other]
            other_size = len(other_grams)
            # Size-ratio upper bound on Jaccard — cheap reject before intersect.
            if min(size, other_size) < threshold * max(size, other_size):
                continue
            score = jaccard(bigrams, other_grams)
            if score >= threshold:
                pairs.append(NearDuplicatePair(edge[0], edge[1], score))

    pairs.sort(key=lambda p: (-p.similarity, p.left, p.right))
    return pairs


def cluster_pairs(pairs: Sequence[NearDuplicatePair]) -> list[list[int]]:
    """Group near-duplicate pairs into connected components (union-find).

    Transitivity is assumed: if A~B and B~C, all three merge into one record
    even when A~C falls below the threshold. That is the right call for a
    memory store — three phrasings of one fact should collapse to one unit —
    but it does mean a low ``threshold`` can chain unrelated records together.
    Hence the conservative default and the mandatory preview before applying.

    Returns clusters of size >= 2, each sorted ascending, ordered by first key.
    """
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:  # path compression
            parent[x], x = root, parent[x]
        return root

    for left, right, _ in pairs:
        a, b = find(left), find(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    groups: dict[int, list[int]] = {}
    for key in parent:
        groups.setdefault(find(key), []).append(key)

    clusters = [sorted(members) for members in groups.values() if len(members) > 1]
    clusters.sort(key=lambda members: members[0])
    return clusters
