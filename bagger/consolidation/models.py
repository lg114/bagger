"""Domain model for a distilled memory record.

A ``MemoryRecord`` is a durable, reusable cognitive unit pulled out of a raw
conversation — the thing that makes bagger a memory store instead of a search
engine. ``MemoryType`` is the closed vocabulary of record kinds; extend it here
if phase-2/3 work needs new kinds (e.g. ``question``, ``todo``).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


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
