"""Merge and de-duplication engine for distilled memory records.

Three distinct operations, ordered by certainty and cost:

**L0 — intra-batch.** Two records the model emitted in the *same* chunk are
collapsed at validation time (``validation.coerce_records``). Cheapest, no IO.

**L1 — exact global.** A new extraction whose type+content fingerprint already
exists in ``memory_records`` is *not* a new row — it is reinforcing an existing
belief. We merge: keep the higher confidence, union the topics, bump
``merge_count``, and append a provenance line so the audit trail still shows
every session that confirmed the fact. This is the operation that makes the
feature earn its name: one memory, many confirmations, no row explosion.

**L2 — fuzzy global.** Paraphrases that survive normalization (different words,
same idea) need a similarity scan. This is lossy — merging destroys the loser's
wording — so it is **never automatic**. ``find_fuzzy_clusters`` only computes
candidates; the caller previews them (``--dry-run``) and commits explicitly
(``--apply``). A conservative default threshold plus a mandatory preview keep a
bad run recoverable.

All database touch points are delegated to the caller via callbacks, so the
*merge rules* here are pure and unit-testable without a SQLite connection.
"""

from __future__ import annotations

from collections.abc import Sequence

from bagger.consolidation.models import (
    MemoryRecord,
    MergeCluster,
)
from bagger.consolidation.normalize import (
    DEFAULT_FUZZY_THRESHOLD,
    cluster_pairs,
    find_near_duplicate_pairs,
)

__all__ = [
    "MergeResult",
    "find_fuzzy_clusters",
    "merge_records",
    "merge_topics",
    "plan_merge",
]


def merge_topics(*groups: Sequence[str]) -> list[str]:
    """Union topic lists, deduplicated case-insensitively, order-preserving."""
    out: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for topic in group:
            marker = topic.casefold()
            if marker and marker not in seen:
                seen.add(marker)
                out.append(topic)
    return out


def merge_records(
    keeper: MemoryRecord,
    *others: MemoryRecord,
) -> MemoryRecord:
    """Return a merged record with the strongest surviving attributes.

    Confidence is the max across all variants (multiple confirmations never
    lower the score). Topics are unioned. The earliest ``created_at`` and the
    original ``id``/provenance stay on ``keeper``; callers update
    ``merge_count`` and ``updated_at`` alongside.
    """
    all_records = (keeper, *others)
    max_conf = max(r.confidence for r in all_records)
    merged_topic_strs = [t for r in all_records for t in r.topics]
    event_id = next((r.event_id for r in all_records if r.event_id), keeper.event_id)
    return keeper.model_copy(
        update={
            "confidence": max_conf,
            "topics": merge_topics(*merged_topic_strs),
            "event_id": event_id,
        }
    )


class MergeResult:
    """Outcome of folding one new record into an existing one (L1).

    ``merged`` means a row was reinforced (no new id); ``inserted`` means the
    fingerprint was novel. Returned per record so the caller can tally both.
    """

    def __init__(self, *, record_id: int, merged: bool, record: MemoryRecord) -> None:
        self.record_id = record_id
        self.merged = merged
        self.record = record


def find_fuzzy_clusters(
    records: Sequence[dict],
    threshold: float = DEFAULT_FUZZY_THRESHOLD,
) -> tuple[list[MergeCluster], int]:
    """Cluster near-duplicate records across the whole table.

    Args:
        records: Rows as ``dict``/mapping with at least ``id``, ``type``,
            ``content`` (and, for display only, ``topics``). Archived records
            are skipped by the caller; pass the live set only.
        threshold: Jaccard cutoff; see ``normalize.DEFAULT_FUZZY_THRESHOLD``.

    Returns:
        ``(clusters, pairs_considered)``. Each cluster names the canonical
        keeper (lowest id) and lists the duplicate ids/contents found under it.
        Transitive pairs are unioned into connected components.
    """
    items = [(r["id"], r["type"], r["content"]) for r in records]
    pairs = find_near_duplicate_pairs(items, threshold=threshold)
    components = cluster_pairs(pairs)

    by_id = {r["id"]: r for r in records}
    min_sim: dict[int, float] = {}
    for left, right, sim in pairs:
        for key in (left, right):
            min_sim[key] = min(min_sim.get(key, sim), sim)

    clusters: list[MergeCluster] = []
    for members in components:
        keeper_id = members[0]
        keeper = by_id[keeper_id]
        dup_ids = members[1:]
        clusters.append(
            MergeCluster(
                keeper_id=keeper_id,
                keeper_content=keeper.get("content", ""),
                duplicate_ids=dup_ids,
                duplicate_contents=[by_id[d].get("content", "") for d in dup_ids],
                min_similarity=min_sim.get(keeper_id, threshold),
                merged_topics=merge_topics(
                    keeper.get("topics", "").split(",") if keeper.get("topics") else [],
                    *[
                        (by_id[d].get("topics", "") or "").split(",")
                        for d in dup_ids
                        if by_id[d].get("topics")
                    ],
                ),
            )
        )
    return clusters, len(pairs)


def plan_merge(keeper: dict, duplicates: Sequence[dict]) -> dict:
    """Compute the keeper's post-merge column values. Pure — no IO.

    Rules, chosen so that a merge never loses information a reader would miss:

    * ``confidence`` — max. Independent confirmations do not weaken a belief.
    * ``topics`` — union, order-preserving, capped by the storage format.
    * ``created_at`` — earliest. One memory, dated from when it was first known.
    * ``merge_count`` — sum. How many extractions back this record.
    * ``relevance`` — max, so a fuzzy merge cannot demote a record that phase-3
      forgetting has already scored highly.

    Returns a dict of column -> value for the keeper row. Callers delete the
    duplicate ids and re-point their provenance at ``keeper['id']``.
    """
    group = [keeper, *duplicates]
    topic_lists = [(row.get("topics") or "").split(",") for row in group]
    return {
        "confidence": max(float(row.get("confidence") or 0.0) for row in group),
        "topics": ",".join(merge_topics(*topic_lists)),
        "created_at": min(
            (row.get("created_at") or "" for row in group),
            key=lambda s: s or "\uffff",
        ),
        "merge_count": sum(int(row.get("merge_count") or 1) for row in group),
        "relevance": max(float(row.get("relevance") or 1.0) for row in group),
    }
