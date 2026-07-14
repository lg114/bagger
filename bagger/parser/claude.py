"""Parse Claude Code JSONL transcript files into MemoryEvent list."""

import json
from datetime import datetime
from pathlib import Path

from bagger.models.event import (
    BlockType,
    ContentBlock,
    MemoryEvent,
    Role,
)
from bagger.parser.base import Parser as _Parser
from bagger.parser.base import StandardUsage

# ── Parser implementation ──────────────────────────────────


class ClaudeParser(_Parser):
    """Parser for Claude Code JSONL transcripts (~/.claude/projects/)."""

    SOURCE_NAME = "claude"
    PROJECTS_DIR: Path

    def __init__(self, projects_dir: Path | None = None):
        self.PROJECTS_DIR = projects_dir or Path.home() / ".claude" / "projects"

    @property
    def source_name(self) -> str:
        return self.SOURCE_NAME

    def discover_sessions(self) -> list[Path]:
        """Yield all valid JSONL files, excluding agent-* and warmup."""
        if not self.PROJECTS_DIR.exists():
            return []

        files: list[Path] = []
        for root, _, filenames in _walk(self.PROJECTS_DIR):
            for name in filenames:
                if (
                    name.endswith(".jsonl")
                    and not name.startswith("agent-")
                    and "warmup" not in name.lower()
                ):
                    files.append(Path(root) / name)

        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return files

    def parse(self, path: Path) -> list[MemoryEvent]:
        return _parse_file(path)

    def parse_incremental(self, path: Path, offset: int) -> list[MemoryEvent]:
        return _parse_new_lines(path, offset)

    def normalize_usage(self, raw_usage: dict, raw_model: str | None = None) -> StandardUsage:
        return normalize_claude_usage(raw_usage, raw_model)

    def extract_summary(self, path: Path) -> str:
        return _extract_summary(path)


# ── Module-level functions (backward compat, delegated by ClaudeParser) ──


def _walk(projects_dir: Path):
    """os.walk wrapper (avoids direct os import in public API)."""
    import os

    yield from os.walk(projects_dir)


def _parse_file(path: Path) -> list[MemoryEvent]:
    """Parse a full JSONL file into MemoryEvent objects."""
    events: list[MemoryEvent] = []

    with open(path, encoding="utf-8") as f:
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


def _parse_new_lines(path: Path, offset: int) -> list[MemoryEvent]:
    """Parse only new lines appended after a byte offset."""
    import json as _json

    with open(path, encoding="utf-8") as f:
        f.seek(offset)
        new_lines = f.readlines()

    raw_entries = []
    for line in new_lines:
        line = line.strip()
        if not line:
            continue
        try:
            raw = _json.loads(line)
        except _json.JSONDecodeError:
            continue
        if raw.get("type") in ("user", "assistant"):
            raw_entries.append(raw)

    events = [e for raw in raw_entries if (e := _parse_entry(raw)) is not None]
    return events


def _extract_summary(path: Path) -> str:
    """Extract session summary from the first line of a JSONL file."""
    with open(path, encoding="utf-8") as f:
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
        with open(path, encoding="utf-8") as f:
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
    except (OSError, json.JSONDecodeError):
        pass

    return "(no summary)"


# ── Backward-compat aliases ──
parse_jsonl = _parse_file
extract_summary = _extract_summary


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def normalize_claude_usage(raw_usage: dict, raw_model: str | None = None) -> StandardUsage:
    """Map Claude Code's usage dict to bagger's StandardUsage.

    ``cost_usd`` is stored as-is when present and > 0 (Anthropic backends
    only); bagger never computes cost. Non-Anthropic backends leave it None.
    """
    u = raw_usage or {}
    raw_cost = u.get("cost_usd")
    cost = float(raw_cost) if isinstance(raw_cost, (int, float)) and raw_cost > 0 else None
    return StandardUsage(
        token_input=u.get("input_tokens", 0),
        token_output=u.get("output_tokens", 0),
        token_cache_read=u.get("cache_read_input_tokens", 0),
        token_cache_write=u.get("cache_creation_input_tokens", 0),
        cost_usd=cost,
        currency="USD",
        service_tier=u.get("service_tier"),
    )


def _resolve_provider(model: str | None) -> str | None:
    """Best-effort backend detection from the model name.

    Heuristic only: a non-Anthropic backend reached through a proxy that
    spoofs the model name (e.g. MiMo served as ``claude-*``) will be mislabeled.
    A future config-based ``source_alias`` mapping resolves that — out of scope
    for the price-free subset.
    """
    if not model:
        return None
    m = model.lower()
    if m.startswith("claude") or "anthropic" in m:
        return "anthropic"
    if "xiaomi" in m or m.startswith("mimo"):
        return "xiaomi"
    if m.startswith("gpt") or "openai" in m:
        return "openai"
    if "deepseek" in m:
        return "deepseek"
    return None


def _parse_entry(raw: dict) -> MemoryEvent | None:
    """Parse a single JSONL entry into a MemoryEvent."""
    entry_type = raw["type"]
    msg = raw.get("message", {})
    role_str = msg.get("role", entry_type)
    role = Role(role_str)

    content_blocks = _parse_content(role, msg.get("content", ""))

    usage = msg.get("usage", {}) or {}
    u = normalize_claude_usage(usage, msg.get("model"))

    return MemoryEvent(
        event_id=raw.get("uuid", ""),
        session_id=raw.get("sessionId", ""),
        parent_event_id=raw.get("parentUuid"),
        timestamp=datetime.fromisoformat(
            raw.get("timestamp", "1970-01-01T00:00:00.000Z").replace("Z", "+00:00")
        ),
        role=role,
        content_blocks=content_blocks,
        token_input=u.token_input,
        token_output=u.token_output,
        token_cache_read=u.token_cache_read,
        token_cache_write=u.token_cache_write,
        cost_usd=u.cost_usd,
        currency=u.currency,
        service_tier=u.service_tier,
        cwd=raw.get("cwd"),
        git_branch=raw.get("gitBranch"),
        model=msg.get("model"),
        provider=_resolve_provider(msg.get("model")),
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
            blocks.append(ContentBlock(block_type=BlockType.TEXT, text=item.get("text", "")))
        elif item_type == "thinking":
            blocks.append(
                ContentBlock(block_type=BlockType.THINKING, text=item.get("thinking", ""))
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
                text = " ".join(b.get("text", "") for b in output if isinstance(b, dict))
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
