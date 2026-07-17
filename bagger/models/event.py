"""Core data models for bagger."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class BlockType(StrEnum):
    TEXT = "text"
    THINKING = "thinking"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"


class ContentBlock(BaseModel):
    """A single content block within a message (text, thinking, tool_use, or tool_result)."""

    block_type: BlockType
    text: str | None = None
    tool_name: str | None = None
    tool_id: str | None = None
    tool_input: dict | None = None


class MemoryEvent(BaseModel):
    """A normalized conversation event from any AI coding tool."""

    event_id: str
    session_id: str
    parent_event_id: str | None = None
    timestamp: datetime
    role: Role
    content_blocks: list[ContentBlock] = Field(default_factory=list)
    token_input: int = 0
    token_output: int = 0
    token_cache_read: int = 0
    token_cache_write: int = 0
    cost_usd: float | None = None  # only stored, never computed by bagger
    currency: str = "USD"
    service_tier: str | None = None
    cwd: str | None = None
    git_branch: str | None = None
    model: str | None = None
    provider: str | None = None  # resolved backend (e.g. "anthropic", "xiaomi")


class Session(BaseModel):
    """Metadata about a single Claude Code session."""

    session_id: str
    summary: str
    project_path: str = ""
    message_count: int = 0
    first_message_at: datetime | None = None
    last_message_at: datetime | None = None
    # ── Lineage (ADR-0001, all optional / derived) ──
    parent_session_id: str | None = None
    resume_of: str | None = None
    is_compaction: bool = False
    compaction_of: str | None = None


class WatchState(BaseModel):
    """Persistent state for incremental sync."""

    sessions: dict[str, int] = Field(default_factory=dict)
    """Map of session_id -> last_processed_byte_offset."""
