"""Static phrase-level synonym expansion for memory FTS queries.

Decided 2026-08-26 (OR-expand-narrow, gc 拍板): a small hand-curated table
maps query phrases to expansion tokens that are appended to the memory-FTS
OR token set. This closes lexical-recall gaps where the corpus simply never
uses the queried word (``瘦身`` appears in 0 memories while the relevant
docs say ``sidecar`` / ``打包``).

Design constraints (from the double-corpus experiment):

- **Phrase-level matching only**: expansion fires when the *full phrase*
  (e.g. ``不联网``) appears verbatim in the raw query. Token-level matching
  on ``联网`` would wrongly fire on antonym docs ("联网检查受限").
- **Zero coverage words are excluded**: ``离线`` (0 docs) and ``本地优先``
  (jieba splits it into 本地/优先 at index time, so the phrase never
  matches) must not enter the table; ``体积`` currently matches noise only.
- **Deterministic and offline**: pure substring matching over a static
  table — CI-reproducible, no embedder dependency.
- Queries that trigger no expansion keep the exact original token list, so
  behavior for unrelated queries is unchanged by construction.

The table is deliberately tiny. Every entry must be validated against the
real corpus with ``scripts/exp_query_expansion.py`` (fixture + ``--prod``
double run) before it is added — see the tuning lessons in the project
memory: fixture-only conclusions do not transfer.
"""

from __future__ import annotations

# phrase (must appear verbatim in the raw query) -> expansion tokens.
# Tokens must be single FTS tokens as they occur in the jieba-indexed
# corpus (compound phrases like 本地优先 never survive tokenization).
MEMORY_QUERY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "瘦身": ("sidecar", "打包"),
    "不联网": ("本地",),
}

# Conflict / antonym lexicon (gc-signed 2026-08-27). For a phrase that
# triggers expansion, these words signal the *opposite* of the query intent.
# When present in a recalled doc they mark it as an antonym and it is demoted
# (moved to the end of the result list) so it cannot be pushed to rank 1 by
# the expansion token alone. Curated by hand against the real corpus; every
# entry must be validated with scripts/exp_rerank.py before being added.
MEMORY_QUERY_CONFLICTS: dict[str, tuple[str, ...]] = {
    "不联网": ("联网检查", "受限", "沙箱"),
}


def expand_terms(
    query: str,
    table: dict[str, tuple[str, ...]] | None = None,
) -> list[str]:
    """Return expansion tokens for phrases found verbatim in ``query``.

    Order is deterministic (table order), duplicates across phrases are
    deduplicated while preserving first occurrence. Pure function: no I/O,
    no tokenization — the caller appends the returned tokens to its OR set.
    """
    source = MEMORY_QUERY_SYNONYMS if table is None else table
    out: list[str] = []
    for phrase, expansions in source.items():
        if phrase in query:
            for token in expansions:
                if token not in out:
                    out.append(token)
    return out


def conflict_words_for(
    query: str,
    table: dict[str, tuple[str, ...]] | None = None,
) -> tuple[str, ...] | None:
    """Return conflict/antonym words for a phrase found verbatim in ``query``.

    Returns ``None`` when no expansion phrase is present, so queries that
    trigger no expansion are never touched. Pure function: no I/O.
    """
    source = MEMORY_QUERY_CONFLICTS if table is None else table
    for phrase, words in source.items():
        if phrase in query:
            return words
    return None
