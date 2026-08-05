"""Markdown exporter: render a single session into readable Markdown.

``render_session_markdown`` / ``render_session`` are pure functions over a
session dict + its event dicts, used directly by the API and CLI to return a
Markdown string. ``MarkdownExporter`` wraps that same renderer to satisfy the
event-stream ``Exporter`` ABC (used by ``JsonlExporter`` for backup), so a
Markdown export is a first-class ``Exporter`` too — even though, unlike JSONL,
it is session-scoped (one file per session, rendered on flush).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from bagger.exporters.base import Exporter
from bagger.models.event import BlockType, MemoryEvent

# Render-layer cap for human-readable Markdown output. Deliberately *much*
# smaller than the storage-layer cap (32KB, ``bagger.parsers._common.
# TOOL_RESULT_MAX_CHARS``): the database retains full tool_result fidelity,
# while the exported .md is meant for skimming, so a 2KB ceiling keeps it
# readable instead of a multi-megabyte paste of file contents / command output.
# The two caps are intentionally different layers and are NOT unified into one
# value — collapsing them would either bloat the DB (at 2KB) or the .md (at 32KB).
MARKDOWN_RENDER_TOOL_RESULT_CAP = 2000

# Formats the exporter understands today. "zvec" / structured-summary are
# roadmap items; adding one is just another branch in ``render_session``.
SUPPORTED_FORMATS = ("markdown",)


def _fmt_ts(value: object) -> str:
    """Render an ISO timestamp (str or datetime) as 'YYYY-MM-DD HH:MM'."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    text = str(value or "")
    if not text:
        return ""
    # 2026-08-04T12:34:56[.123456][+00:00] -> 2026-08-04 12:34
    return text[:16].replace("T", " ")


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n\n… ({len(text) - limit} more characters truncated)"


def _render_block(block: dict, max_tool_result_chars: int) -> str:
    """Render a single content block (parsed from content_json) to Markdown."""
    block_type = block.get("block_type", "")
    text = block.get("text") or ""

    if block_type == "thinking":
        if not text:
            return ""
        # Blockquote keeps thinking visually distinct but skimmable.
        lines = ["> 💭 **thinking**", *[f"> {ln}" for ln in text.split("\n")]]
        return "\n".join(lines)

    if block_type == "tool_use":
        name = block.get("tool_name") or "tool"
        tool_input = block.get("tool_input")
        header = f"**🔧 {name}**"
        # Surface the edited/read path up front when present.
        fp = None
        if isinstance(tool_input, dict):
            fp = tool_input.get("file_path") or tool_input.get("path")
        if fp:
            header += f" — `{fp}`"
        if tool_input is None:
            return header
        try:
            pretty = json.dumps(tool_input, indent=2, ensure_ascii=False)
        except (TypeError, ValueError):
            pretty = str(tool_input)
        return f"{header}\n\n```json\n{pretty}\n```"

    if block_type == "tool_result":
        name = block.get("tool_name") or "tool"
        label = f"> 📎 **result** ({name}):" if name else "> 📎 **result**:"
        if not text:
            return f"{label} _(empty)_"
        body = _truncate(text, max_tool_result_chars)
        return "\n".join([label, *[f"> {ln}" for ln in body.split("\n")]])

    # Plain text (block_type == "text" or anything else) → verbatim.
    return text


def render_session_markdown(
    session: dict,
    events: list[dict],
    *,
    include_meta: bool = True,
    max_tool_result_chars: int = MARKDOWN_RENDER_TOOL_RESULT_CAP,
) -> str:
    """Render ``session`` + its ``events`` into a readable Markdown document.

    Args:
        session: dict from ``storage.get_session`` (keys: id, source, summary,
            project_path, message_count, first_message_at, last_message_at).
        events: list of event dicts, each with ``role``, ``timestamp``,
            ``content_json`` (JSON string) and optional ``content_text``,
            ``model``, ``token_input``, ``token_output``, ``cost_usd``.
        include_meta: emit the session metadata block at the top.
        max_tool_result_chars: cap tool_result text length for readability.

    Returns:
        A Markdown string.
    """
    out: list[str] = []

    summary = session.get("summary") or "(no summary)"
    out.append(f"# {summary}")
    out.append("")

    if include_meta:
        sid = session.get("id") or session.get("session_id") or ""
        source = session.get("source") or "unknown"
        project = session.get("project_path") or "—"
        count = session.get("message_count", len(events))
        meta_lines = [
            f"- **Source:** {source}",
            f"- **Session ID:** `{sid}`",
            f"- **Project:** {project}",
            f"- **Messages:** {count}",
            f"- **First:** {_fmt_ts(session.get('first_message_at'))}",
            f"- **Last:** {_fmt_ts(session.get('last_message_at'))}",
        ]
        if events:
            last_model = next((e.get("model") for e in reversed(events) if e.get("model")), None)
            if last_model:
                meta_lines.append(f"- **Model:** {last_model}")
        out.append("\n".join(meta_lines))
        out.append("")
        out.append("---")
        out.append("")

    for ev in events:
        role = ev.get("role")
        ts = _fmt_ts(ev.get("timestamp"))
        if role == "user":
            out.append(f"## 👤 User — {ts}")
        elif role == "assistant":
            out.append(f"## 🤖 Assistant — {ts}")
        else:
            out.append(f"## {role} — {ts}")
        out.append("")

        # Prefer structured blocks; fall back to raw text if JSON is missing/broken.
        raw = ev.get("content_json")
        blocks: list[dict] = []
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    blocks = parsed
            except (json.JSONDecodeError, TypeError):
                blocks = []
        if not blocks:
            text_fallback = ev.get("content_text") or ""
            if text_fallback:
                blocks = [{"block_type": "text", "text": text_fallback}]

        for block in blocks:
            rendered = _render_block(block, max_tool_result_chars)
            if rendered:
                out.append(rendered)
                out.append("")

        # Lightweight token/cost footnote for assistant turns.
        tin = ev.get("token_input") or 0
        tout = ev.get("token_output") or 0
        cost = ev.get("cost_usd")
        if (tin or tout) and role == "assistant":
            note = f"_tokens: in {tin:,} · out {tout:,}_"
            if cost:
                note += f" · _cost ${cost:.4f}_"
            out.append(note)
            out.append("")

    out.append("---")
    out.append("")
    out.append(
        "_Exported by **bagger** from local agent transcripts. "
        "Your data never leaves this machine._"
    )
    out.append("")

    return "\n".join(out)


def render_session(
    session: dict,
    events: list[dict],
    fmt: str = "markdown",
    **kwargs,
) -> str:
    """Dispatch to the renderer for ``fmt``. Single entry point for API/CLI.

    Raises:
        ValueError: if ``fmt`` is not in ``SUPPORTED_FORMATS``.
    """
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported export format '{fmt}'. Supported: {', '.join(SUPPORTED_FORMATS)}"
        )
    return render_session_markdown(session, events, **kwargs)


# ── Exporter ABC implementation ──────────────────────────────


def _event_to_render_dict(event: MemoryEvent) -> dict:
    """Convert a ``MemoryEvent`` to the storage-shape dict the renderer expects.

    Mirrors ``SqliteEventRepository._event_params`` so a ``MarkdownExporter``
    produces byte-for-byte the same Markdown as the API/CLI do from the database:
    ``content_json`` is the serialized ``content_blocks`` list and ``content_text``
    is the FTS-extraction fallback used when JSON is missing.
    """
    content_json = json.dumps([b.model_dump() for b in event.content_blocks], ensure_ascii=False)
    text_parts: list[str] = []
    for b in event.content_blocks:
        if b.block_type in (BlockType.TEXT, BlockType.THINKING) and b.text:
            text_parts.append(b.text)
        elif b.block_type == BlockType.TOOL_USE:
            text_parts.append(f"[tool_use:{b.tool_name}]")
        elif b.block_type == BlockType.TOOL_RESULT and b.text:
            text_parts.append(f"[tool_result:{b.text[:200]}]")
    content_text = " ".join(text_parts)
    ts = (
        event.timestamp.isoformat()
        if isinstance(event.timestamp, datetime)
        else str(event.timestamp)
    )
    return {
        "role": event.role.value,
        "timestamp": ts,
        "content_json": content_json,
        "content_text": content_text,
        "model": event.model,
        "token_input": event.token_input,
        "token_output": event.token_output,
        "cost_usd": event.cost_usd,
    }


class MarkdownExporter(Exporter):
    """Session-scoped Markdown exporter implementing the ``Exporter`` ABC.

    Unlike ``JsonlExporter`` (which streams one event per line to a file), a
    Markdown document needs the whole session rendered in reading order, so
    events are buffered via :meth:`export_event` and the file is written once on
    :meth:`flush`. The session dict is supplied up front (as to
    ``render_session_markdown``).
    """

    def __init__(self, path: Path, session: dict):
        self._path = path
        self._session = session
        self._events: list[MemoryEvent] = []

    def export_event(self, event: MemoryEvent) -> None:
        self._events.append(event)

    def render(self) -> str:
        """Render buffered events into a Markdown string (no file I/O)."""
        events = [_event_to_render_dict(e) for e in self._events]
        return render_session_markdown(self._session, events)

    def flush(self) -> None:
        body = self.render()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(body, encoding="utf-8")

    def close(self) -> None:
        """Flush and release. Safe to call multiple times (mirrors JsonlExporter)."""
        self.flush()
