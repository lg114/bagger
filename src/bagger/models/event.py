"""Core data models for bagger."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Role(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class BlockType(str, Enum):
    TEXT = "text"
    THINKING = "thinking"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"


class ContentBlock(BaseModel):
    """A single content block within a message (text, thinking, tool_use, or tool_result)."""

    block_type: BlockType
    text: Optional[str] = None
    tool_name: Optional[str] = None
    tool_id: Optional[str] = None
    tool_input: Optional[dict] = None


class MemoryEvent(BaseModel):
    """A normalized conversation event from any AI coding tool."""

    event_id: str
    session_id: str
    parent_event_id: Optional[str] = None
    timestamp: datetime
    role: Role
    content_blocks: list[ContentBlock] = Field(default_factory=list)
    token_input: int = 0
    token_output: int = 0
    cwd: Optional[str] = None
    git_branch: Optional[str] = None
    model: Optional[str] = None


class Session(BaseModel):
    """Metadata about a single Claude Code session."""

    session_id: str
    summary: str
    project_path: str = ""
    message_count: int = 0
    first_message_at: Optional[datetime] = None
    last_message_at: Optional[datetime] = None


class WatchState(BaseModel):
    """Persistent state for incremental sync."""

    sessions: dict[str, int] = Field(default_factory=dict)
    """Map of session_id -> last_processed_byte_offset."""
