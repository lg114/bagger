"""Parse Claude Code JSONL transcript files into MemoryEvent list."""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from bagger.models.event import (
    BlockType,
    ContentBlock,
    MemoryEvent,
    Role,
)


def parse_jsonl(path: Path) -> list[MemoryEvent]:
    """Parse a Claude Code JSONL file into normalized MemoryEvent objects.

    Handles entry types: summary, user, assistant, file-history-snapshot.
    Returns only user and assistant events.
    """
    events: list[MemoryEvent] = []

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_type = raw.get("type")
            if entry_type not in ("user", "assistant"):
                continue

            event = _parse_entry(raw)
            if event:
                events.append(event)

    return events


def extract_summary(path: Path) -> str:
    """Extract session summary from the first line of a JSONL file."""
    with open(path, "r", encoding="utf-8") as f:
        first_line = f.readline().strip()
    if not first_line:
        return "(no summary)"
    try:
        data = json.loads(first_line)
    except json.JSONDecodeError:
        return "(no summary)"

    if data.get("type") == "summary":
        summary = data.get("summary", "")
        if summary:
            return _truncate(summary, 120)

    # Fallback: try first user message
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                data = json.loads(line.strip())
                if data.get("type") == "user":
                    content = data.get("message", {}).get("content", "")
                    if isinstance(content, str):
                        return _truncate(content, 120)
                    if isinstance(content, list) and content:
                        first_block = content[0]
                        text = first_block.get("text", "")
                        if text:
                            return _truncate(text, 120)
                    break
    except (json.JSONDecodeError, IOError):
        pass

    return "(no summary)"


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _parse_entry(raw: dict) -> Optional[MemoryEvent]:
    """Parse a single JSONL entry into a MemoryEvent."""
    entry_type = raw["type"]
    msg = raw.get("message", {})
    role_str = msg.get("role", entry_type)
    role = Role(role_str)

    content_blocks = _parse_content(role, msg.get("content", ""))

    usage = msg.get("usage", {}) or {}
    token_input = usage.get("input_tokens", 0)
    token_output = usage.get("output_tokens", 0)

    return MemoryEvent(
        event_id=raw.get("uuid", ""),
        session_id=raw.get("sessionId", ""),
        parent_event_id=raw.get("parentUuid"),
        timestamp=datetime.fromisoformat(
            raw.get("timestamp", "1970-01-01T00:00:00.000Z").replace("Z", "+00:00")
        ),
        role=role,
        content_blocks=content_blocks,
        token_input=token_input,
        token_output=token_output,
        cwd=raw.get("cwd"),
        git_branch=raw.get("gitBranch"),
        model=msg.get("model"),
    )


def _parse_content(role: Role, content: str | list) -> list[ContentBlock]:
    """Parse message content into ContentBlock list."""
    blocks: list[ContentBlock] = []

    if isinstance(content, str):
        blocks.append(ContentBlock(block_type=BlockType.TEXT, text=content))
        return blocks

    if not isinstance(content, list):
        return blocks

    tool_counter = 0
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type", "")

        if item_type == "text":
            blocks.append(
                ContentBlock(block_type=BlockType.TEXT, text=item.get("text", ""))
            )
        elif item_type == "thinking":
            blocks.append(
                ContentBlock(
                    block_type=BlockType.THINKING, text=item.get("thinking", "")
                )
            )
        elif item_type == "tool_use":
            tool_counter += 1
            blocks.append(
                ContentBlock(
                    block_type=BlockType.TOOL_USE,
                    tool_name=item.get("name", "unknown"),
                    tool_id=item.get("id", f"tool_{tool_counter}"),
                    tool_input=item.get("input", {}),
                )
            )
        elif item_type == "tool_result":
            tool_counter += 1
            output = item.get("content", "")
            if isinstance(output, list):
                text = " ".join(
                    b.get("text", "") for b in output if isinstance(b, dict)
                )
            else:
                text = str(output)
            blocks.append(
                ContentBlock(
                    block_type=BlockType.TOOL_RESULT,
                    tool_id=item.get("tool_use_id", f"tool_{tool_counter}"),
                    text=text,
                )
            )

    return blocks
