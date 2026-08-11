"""Domain models for memory extraction and consolidation.

A ``MemoryRecord`` is a durable, reusable cognitive unit pulled out of a raw
conversation — the thing that makes bagger a memory store instead of a search
engine. ``MemoryType`` is the closed vocabulary of record kinds; extend it here
if phase-2/3 work needs new kinds (e.g. ``question``, ``todo``).

The rest of this module is the *reporting* surface. A consolidation run touches
a network API, an LLM's judgement and a database, so "it worked" is not a
boolean — records get rejected, chunks fail, duplicates merge. Every one of
those outcomes is counted and returned rather than printed, which keeps the
library silent (the CLI owns presentation) and makes the pipeline assertable in
tests.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from bagger.consolidation.normalize import content_fingerprint


class MemoryType(StrEnum):
    """The four record kinds phase-1 extraction recognizes.

    - fact:        an objective fact / known piece of information
    - preference:  a stated preference / habit / taste
    - decision:    a decision made / a choice between options
    - lesson:      a lesson learned / a pitfall hit / hard-won experience
    """

    FACT = "fact"
    PREFERENCE = "preference"
    DECISION = "decision"
    LESSON = "lesson"


class MemoryRecord(BaseModel):
    """A single distilled memory unit, ready to persist into ``memory_records``."""

    type: MemoryType
    content: str = Field(..., min_length=1)
    topics: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    # Provenance — filled by the Consolidator, not the LLM.
    source: str = "claude"
    session_id: str = ""
    event_id: str | None = None  # primary source event (may be None)
    created_at: str | None = None
    # Phase-3 (forgetting) fields — populated on insert, used later.
    relevance: float = 1.0
    archived: bool = False

    @property
    def fingerprint(self) -> str:
        """Type-scoped content hash — the exact-duplicate key."""
        return content_fingerprint(self.type.value, self.content)


class RejectReason(StrEnum):
    """Why a record emitted by the LLM did not make it into the database."""

    NOT_AN_OBJECT = "not_an_object"
    UNKNOWN_TYPE = "unknown_type"
    EMPTY_CONTENT = "empty_content"
    CONTENT_TOO_SHORT = "content_too_short"
    DUPLICATE_IN_BATCH = "duplicate_in_batch"


class RejectedRecord(BaseModel):
    """A dropped record plus enough context to debug the prompt that caused it.

    Kept as data (not a log line) so ``bagger consolidate`` can show a sample
    and a test can assert on the reason without capturing stdout.
    """

    reason: RejectReason
    detail: str = ""
    excerpt: str = ""


class ChunkFailure(BaseModel):
    """One chunk that could not be extracted, after retries were exhausted."""

    source: str
    session_id: str
    chunk_index: int
    error: str
    retryable: bool = False


class ConsolidationReport(BaseModel):
    """Everything a caller needs to know about one ``Consolidator.run``.

    ``records_merged`` is the headline consolidation metric: extractions that
    matched an existing memory and reinforced it instead of adding a row.
    """

    sessions_seen: int = 0
    sessions_processed: int = 0
    sessions_skipped: int = 0
    sessions_failed: int = 0

    chunks_total: int = 0
    chunks_ok: int = 0
    chunks_failed: int = 0

    records_extracted: int = 0  # survived validation
    records_inserted: int = 0  # new rows in memory_records
    records_merged: int = 0  # folded into an existing row
    records_rejected: int = 0  # dropped by validation

    by_type: dict[str, int] = Field(default_factory=dict)
    rejects: list[RejectedRecord] = Field(default_factory=list)
    failures: list[ChunkFailure] = Field(default_factory=list)
    previews: list[str] = Field(default_factory=list)
    elapsed_seconds: float = 0.0
    interrupted: bool = False

    @property
    def ok(self) -> bool:
        """True when nothing failed. Useful as a CLI exit-code predicate."""
        return self.chunks_failed == 0 and self.sessions_failed == 0


class ProgressEvent(BaseModel):
    """A single step worth reporting to a human while a long run proceeds.

    Emitted through a callback so the library never writes to stdout; the CLI
    renders these with ``click.echo`` and a test can collect them into a list.
    """

    kind: str  # session_start | session_done | session_skip | chunk_error
    source: str = ""
    session_id: str = ""
    message: str = ""
    events: int = 0
    inserted: int = 0
    merged: int = 0


class MergeCluster(BaseModel):
    """A group of near-duplicate records proposed for (or committed to) a merge."""

    keeper_id: int
    keeper_content: str
    duplicate_ids: list[int]
    duplicate_contents: list[str] = Field(default_factory=list)
    min_similarity: float = 0.0
    merged_topics: list[str] = Field(default_factory=list)


class DedupReport(BaseModel):
    """Outcome of a fuzzy dedup pass over ``memory_records``."""

    scanned: int = 0
    clusters: list[MergeCluster] = Field(default_factory=list)
    records_merged: int = 0
    dry_run: bool = True
    threshold: float = 0.0

    @property
    def cluster_count(self) -> int:
        return len(self.clusters)
