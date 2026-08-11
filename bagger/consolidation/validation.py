"""Validation and coercion of raw LLM output into :class:`MemoryRecord`.

Everything crossing this boundary is untrusted. The model is instructed to
return a specific JSON shape, but instruction-following is probabilistic: it
will occasionally emit ``"Fact"`` instead of ``"fact"``, a comma-separated
string where a list was asked for, a confidence of ``"high"``, an ``event_id``
it invented, or a 3000-character verbatim quote of the transcript.

The original implementation wrapped construction in
``except (ValueError, KeyError, TypeError): continue`` — every one of those
mistakes silently cost a record, with no way to tell a hallucinating model from
a working one. This module replaces that with an explicit policy:

* **Repair what is unambiguous** — case, aliases, list-vs-string, out-of-range
  confidence, over-long content. Throwing away a good insight because the model
  wrote "Fact" is a worse failure than accepting it.
* **Reject what is not** — unknown types, empty or single-token content.
* **Always say why** — every drop returns a :class:`RejectedRecord`, so the run
  report can distinguish "the model produced nothing useful" from "the model
  produced plenty and we discarded it".

Two rules exist purely to protect downstream storage:

* ``topics`` are persisted as a comma-joined string in a single column, so a
  topic containing a comma would silently split into two on read. Separators
  inside a topic are rewritten to spaces at the boundary rather than trusted.
* ``event_id`` is checked against the event ids actually present in the chunk.
  A hallucinated id is not a harmless string — it breaks provenance, the one
  property that makes a distilled memory auditable back to its transcript.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from bagger.consolidation.models import (
    MemoryRecord,
    MemoryType,
    RejectedRecord,
    RejectReason,
)
from bagger.consolidation.normalize import content_fingerprint

__all__ = [
    "MAX_CONTENT_CHARS",
    "MAX_TOPICS",
    "MAX_TOPIC_CHARS",
    "MIN_CONTENT_CHARS",
    "coerce_records",
    "normalize_topics",
]

# A distilled record is a note, not a transcript. The live corpus averages 57
# characters; 500 leaves ample headroom for a dense multi-clause fact while
# capping the damage when the model pastes back a whole code block.
MAX_CONTENT_CHARS = 500
# Below this, content carries no standalone meaning ("ok", "见上").
MIN_CONTENT_CHARS = 4
MAX_TOPICS = 8
MAX_TOPIC_CHARS = 24

# Aliases observed from real models plus the obvious near-misses. Keys are
# casefolded; the Chinese forms matter because the prompt itself is Chinese and
# smaller models mirror its language back in the ``type`` field.
_TYPE_ALIASES: dict[str, MemoryType] = {
    "fact": MemoryType.FACT,
    "facts": MemoryType.FACT,
    "info": MemoryType.FACT,
    "information": MemoryType.FACT,
    "knowledge": MemoryType.FACT,
    "observation": MemoryType.FACT,
    "事实": MemoryType.FACT,
    "信息": MemoryType.FACT,
    "preference": MemoryType.PREFERENCE,
    "preferences": MemoryType.PREFERENCE,
    "pref": MemoryType.PREFERENCE,
    "habit": MemoryType.PREFERENCE,
    "taste": MemoryType.PREFERENCE,
    "偏好": MemoryType.PREFERENCE,
    "习惯": MemoryType.PREFERENCE,
    "decision": MemoryType.DECISION,
    "decisions": MemoryType.DECISION,
    "choice": MemoryType.DECISION,
    "conclusion": MemoryType.DECISION,
    "决定": MemoryType.DECISION,
    "决策": MemoryType.DECISION,
    "选型": MemoryType.DECISION,
    "lesson": MemoryType.LESSON,
    "lessons": MemoryType.LESSON,
    "lesson_learned": MemoryType.LESSON,
    "lesson-learned": MemoryType.LESSON,
    "learning": MemoryType.LESSON,
    "pitfall": MemoryType.LESSON,
    "mistake": MemoryType.LESSON,
    "教训": MemoryType.LESSON,
    "经验": MemoryType.LESSON,
    "坑": MemoryType.LESSON,
}

_WHITESPACE = re.compile(r"\s+")
# Anything that would corrupt the comma-joined ``topics`` column, plus the CJK
# enumeration comma that Chinese models reach for by default.
_TOPIC_SEPARATORS = re.compile(r"[,，、;；|]+")


def _clean_text(value: Any) -> str:
    """Coerce to ``str`` and collapse whitespace runs into single spaces."""
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    return _WHITESPACE.sub(" ", text).strip()


def _coerce_type(value: Any) -> MemoryType | None:
    key = _clean_text(value).casefold()
    if not key:
        return None
    if hit := _TYPE_ALIASES.get(key):
        return hit
    # "type: fact (objective)" and similar decorated values.
    head = re.split(r"[\s(（/:：-]", key, maxsplit=1)[0]
    return _TYPE_ALIASES.get(head)


def _coerce_confidence(value: Any) -> float:
    """Clamp to [0, 1]; unparseable or non-finite values fall back to 0.5.

    A bad confidence is never a reason to drop an otherwise good record — the
    insight is the payload, the score is metadata.
    """
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.5
    if math.isnan(score) or math.isinf(score):
        return 0.5
    return min(1.0, max(0.0, score))


def normalize_topics(value: Any) -> list[str]:
    """Normalize ``topics`` into a bounded, storage-safe, deduplicated list.

    Accepts a list, or a single string using any common separator. Embedded
    separators are rewritten to spaces so the comma-joined storage format stays
    unambiguous on read-back.
    """
    if value is None:
        raw_items: list[Any] = []
    elif isinstance(value, str):
        raw_items = list(_TOPIC_SEPARATORS.split(value))
    elif isinstance(value, Mapping):
        raw_items = list(value.keys())
    elif isinstance(value, Iterable):
        raw_items = list(value)
    else:
        raw_items = [value]

    out: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        # Split again: a list element may itself be "存储, 性能".
        for part in _TOPIC_SEPARATORS.split(_clean_text(item)):
            topic = _WHITESPACE.sub(" ", part).strip()
            if not topic:
                continue
            topic = topic[:MAX_TOPIC_CHARS].strip()
            marker = topic.casefold()
            if marker in seen:
                continue
            seen.add(marker)
            out.append(topic)
            if len(out) >= MAX_TOPICS:
                return out
    return out


def coerce_records(
    raw: Any,
    *,
    source: str,
    session_id: str,
    valid_event_ids: Sequence[str] | set[str] | None = None,
) -> tuple[list[MemoryRecord], list[RejectedRecord]]:
    """Turn an LLM payload into validated records plus an audit of every drop.

    Args:
        raw: Whatever the client returned — expected to be a list of dicts, but
            defensively handles anything.
        source: Provenance stamp for the surviving records.
        session_id: Provenance stamp for the surviving records.
        valid_event_ids: Event ids present in the chunk that produced ``raw``.
            Ids outside this set are treated as hallucinations and cleared to
            ``None``. Pass ``None`` to skip the check (used by callers that do
            not have the chunk at hand).

    Returns:
        ``(records, rejects)``. Records are de-duplicated within the batch by
        type-scoped content fingerprint, keeping the highest-confidence variant
        and folding the loser's topics into it.
    """
    rejects: list[RejectedRecord] = []
    if not isinstance(raw, list):
        rejects.append(
            RejectedRecord(
                reason=RejectReason.NOT_AN_OBJECT,
                detail=f"expected a list of records, got {type(raw).__name__}",
                excerpt=_clean_text(raw)[:120],
            )
        )
        return [], rejects

    known_ids = set(valid_event_ids) if valid_event_ids is not None else None
    # fingerprint -> position in ``records``, for intra-batch deduplication.
    index: dict[str, int] = {}
    records: list[MemoryRecord] = []

    for item in raw:
        if not isinstance(item, Mapping):
            rejects.append(
                RejectedRecord(
                    reason=RejectReason.NOT_AN_OBJECT,
                    detail=f"record is {type(item).__name__}, not an object",
                    excerpt=_clean_text(item)[:120],
                )
            )
            continue

        content = _clean_text(item.get("content") or item.get("text"))
        record_type = _coerce_type(item.get("type") or item.get("kind"))
        if record_type is None:
            rejects.append(
                RejectedRecord(
                    reason=RejectReason.UNKNOWN_TYPE,
                    detail=f"unrecognized type {item.get('type')!r}",
                    excerpt=content[:120],
                )
            )
            continue
        if not content:
            rejects.append(
                RejectedRecord(reason=RejectReason.EMPTY_CONTENT, detail="content is empty")
            )
            continue
        if len(content) < MIN_CONTENT_CHARS:
            rejects.append(
                RejectedRecord(
                    reason=RejectReason.CONTENT_TOO_SHORT,
                    detail=f"{len(content)} chars < {MIN_CONTENT_CHARS}",
                    excerpt=content,
                )
            )
            continue
        if len(content) > MAX_CONTENT_CHARS:
            # Truncate rather than drop: an over-long record is a formatting
            # failure, not a content failure. The ellipsis marks it for review.
            content = content[: MAX_CONTENT_CHARS - 1].rstrip() + "…"

        event_id = _clean_text(item.get("event_id")) or None
        if event_id is not None and known_ids is not None and event_id not in known_ids:
            event_id = None  # hallucinated provenance — better absent than wrong

        record = MemoryRecord(
            type=record_type,
            content=content,
            topics=normalize_topics(item.get("topics")),
            confidence=_coerce_confidence(item.get("confidence", 0.5)),
            source=source,
            session_id=session_id,
            event_id=event_id,
        )

        fingerprint = record.fingerprint
        if (pos := index.get(fingerprint)) is not None:
            kept = records[pos]
            winner, loser = (
                (record, kept) if record.confidence > kept.confidence else (kept, record)
            )
            merged = winner.model_copy(
                update={
                    "topics": normalize_topics([*winner.topics, *loser.topics]),
                    "event_id": winner.event_id or loser.event_id,
                }
            )
            records[pos] = merged
            rejects.append(
                RejectedRecord(
                    reason=RejectReason.DUPLICATE_IN_BATCH,
                    detail=f"same fingerprint as an earlier record ({fingerprint})",
                    excerpt=loser.content[:120],
                )
            )
            continue

        index[fingerprint] = len(records)
        records.append(record)

    return records, rejects


def fingerprint_of(record: MemoryRecord) -> str:
    """Convenience wrapper mirroring :attr:`MemoryRecord.fingerprint`."""
    return content_fingerprint(record.type.value, record.content)
