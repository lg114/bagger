"""Parse Codex rollout JSONL transcripts into MemoryEvent list.

Codex — the coding agent shipped as the ``codex`` CLI and as the Codex mode of
the unified ChatGPT desktop app (the standalone Codex app was renamed ChatGPT
in July 2026) — writes one append-only rollout file per session under::

    $CODEX_HOME/sessions/YYYY/MM/DD/rollout-{ISO_TS}-{UUID}.jsonl

Each line is an envelope ``{"timestamp", "type", "payload"}``. Three structural
differences from Claude Code transcripts shape this parser:

* Lines carry **no per-event ids** — only the first ``session_meta`` line
  identifies the session. Event ids are synthesized as
  ``"{session_id}:{byte_start}"``, which is deterministic across full and
  incremental parses (a line's byte offset never changes in an append-only
  file), so the ``UNIQUE(source, event_id)`` constraint dedupes correctly.
* Tool calls are **flat pairs linked by ``call_id`` across lines**, not nested
  content blocks.
* ``event_msg/token_count`` reports **cumulative** usage (unless the newer
  ``last_token_usage`` delta is present), so the parser differences it against
  a running baseline and attaches the delta to the last assistant event.
"""

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from bagger.models.event import (
    BlockType,
    ContentBlock,
    MemoryEvent,
    Role,
)
from bagger.parsers._common import (
    iter_complete_lines,
    scandir_files,
    truncate_text,
    truncate_tool_result,
)
from bagger.parsers.base import Parser as _Parser
from bagger.parsers.base import StandardUsage

logger = logging.getLogger(__name__)

# rollout-2026-06-01T09-15-22(-123)-{id}.jsonl — capture the id fragment after
# the timestamp. Only a fallback; the canonical id comes from session_meta.
_ROLLOUT_NAME_RE = re.compile(r"^rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}(?:-\d+)?-(.+)\.jsonl$")

_SUMMARY_MAX_LEN = 120


# ── Parser implementation ──────────────────────────────────


class CodexParser(_Parser):
    """Parser for Codex rollout transcripts (``$CODEX_HOME/sessions/``)."""

    SOURCE_NAME = "codex"

    def __init__(self, codex_home: Path | None = None):
        env_home = os.environ.get("CODEX_HOME")
        self.CODEX_HOME = codex_home or (Path(env_home) if env_home else Path.home() / ".codex")
        self.SESSIONS_DIR = self.CODEX_HOME / "sessions"

    @property
    def source_name(self) -> str:
        return self.SOURCE_NAME

    def watch_root(self) -> Path:
        """Watch the date-partitioned sessions tree recursively."""
        return self.SESSIONS_DIR

    def discover_sessions(self) -> list[Path]:
        """Find rollout files under the sessions tree, newest first.

        A candidate is accepted only when its first line is a ``session_meta``
        envelope — the directory can hold unrelated JSONL. The ``originator``
        string is deliberately *not* inspected: after the 2026 desktop-app
        unification the same agent may write "Codex Desktop" or "ChatGPT*", so
        it is no longer a stable discriminator.
        """
        if not self.SESSIONS_DIR.exists():
            return []

        files: list[Path] = []
        mtimes: list[float] = []
        for entry in scandir_files(self.SESSIONS_DIR):
            if not (entry.name.startswith("rollout-") and entry.name.endswith(".jsonl")):
                continue
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                continue
            path = Path(entry.path)
            if read_session_meta(path) is None:
                continue
            files.append(path)
            mtimes.append(mtime)

        order = sorted(range(len(files)), key=lambda i: mtimes[i], reverse=True)
        return [files[i] for i in order]

    def session_id_for(self, path: Path) -> str:
        """Canonical session id: ``session_meta.id`` (the real UUID), falling
        back to the id fragment of the rollout filename, then the raw stem."""
        meta = read_session_meta(path)
        if meta:
            sid = meta.get("id") or meta.get("session_id")
            if sid:
                return str(sid)
        m = _ROLLOUT_NAME_RE.match(path.name)
        return m.group(1) if m else path.stem

    def parse(self, path: Path) -> list[MemoryEvent]:
        return _parse_rollout(path, 0)

    def parse_incremental(self, path: Path, offset: int) -> list[MemoryEvent]:
        return _parse_rollout(path, offset)

    def extract_summary(self, path: Path) -> str:
        return _extract_summary(path)

    def normalize_usage(self, raw_usage: dict, raw_model: str | None = None) -> StandardUsage:
        return normalize_codex_usage(raw_usage, raw_model)


# ── Module-level helpers ──


def read_session_meta(path: Path) -> dict | None:
    """Return the first line's payload iff it is a ``session_meta`` envelope."""
    try:
        with open(path, "rb") as f:
            first = f.readline()
        data = json.loads(first)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("type") != "session_meta":
        return None
    payload = data.get("payload")
    return payload if isinstance(payload, dict) else None


def normalize_codex_usage(raw_usage: dict, raw_model: str | None = None) -> StandardUsage:
    """Map OpenAI/Codex usage shapes to StandardUsage.

    Handles both the Codex protocol shape (``cached_input_tokens`` at top
    level) and the Responses API shape (``input_tokens_details.cached_tokens``).
    ``cost_usd`` is always None — OpenAI transcripts carry no cost field and
    bagger never computes one.
    """
    u = raw_usage or {}
    details = u.get("input_tokens_details") or {}
    cache_read = u.get("cached_input_tokens") or details.get("cached_tokens") or 0
    return StandardUsage(
        token_input=u.get("input_tokens", 0),
        token_output=u.get("output_tokens", 0),
        token_cache_read=cache_read,
        token_cache_write=0,
        cost_usd=None,
        currency="USD",
    )


@dataclass
class _RolloutState:
    """Mutable per-file context carried across the lines of one rollout."""

    session_id: str = ""
    cwd: str | None = None
    git_branch: str | None = None
    provider: str | None = None
    model: str | None = None
    prev_event_id: str | None = None
    last_assistant: MemoryEvent | None = None
    # Cumulative token baselines for differencing token_count events.
    cum_input: int = 0
    cum_output: int = 0
    cum_cache_read: int = 0


def _parse_rollout(path: Path, offset: int) -> list[MemoryEvent]:
    """Walk a rollout file from ``offset``, emitting conversation events.

    When resuming mid-file (``offset > 0``) the ``session_meta`` line is behind
    us, so the state is seeded from it explicitly — otherwise synthesized event
    ids would fall back to the filename stem and diverge from the ids (and the
    ``Session`` key) produced by a full parse. Two resume artifacts remain,
    both repaired by any full re-scan: the first in-pass event has no
    ``parent_event_id`` (the previous event's byte offset is unknowable from
    here), and token deltas have no baseline/anchor until the first in-pass
    assistant event (see ``_apply_token_count``).
    """
    events: list[MemoryEvent] = []
    state = _RolloutState()
    if offset > 0:
        meta = read_session_meta(path)
        if meta:
            state.session_id = str(meta.get("id") or meta.get("session_id") or "")
            state.cwd = meta.get("cwd")
            git = meta.get("git") if isinstance(meta.get("git"), dict) else {}
            state.git_branch = git.get("branch") or meta.get("git_branch")
            state.provider = meta.get("model_provider")
    for byte_start, line in iter_complete_lines(path, offset):
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        payload = raw.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        _handle_line(raw, payload, state, events, path, byte_start)
    return events


def _handle_line(
    raw: dict,
    payload: dict,
    state: _RolloutState,
    events: list[MemoryEvent],
    path: Path,
    byte_start: int,
) -> None:
    line_type = raw.get("type")
    ts = raw.get("timestamp")

    if line_type == "session_meta":
        state.session_id = str(
            payload.get("id") or payload.get("session_id") or state.session_id or path.stem
        )
        state.cwd = payload.get("cwd") or state.cwd
        git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
        state.git_branch = git.get("branch") or payload.get("git_branch") or state.git_branch
        state.provider = payload.get("model_provider") or state.provider
        return

    if line_type == "turn_context":
        # Emitted at turn start and on every model switch mid-session.
        state.model = payload.get("model") or state.model
        state.cwd = payload.get("cwd") or state.cwd
        return

    if line_type == "response_item":
        _handle_response_item(payload, state, events, path, byte_start, ts)
        return

    if line_type == "event_msg":
        _handle_event_msg(payload, state)
        return
    # compacted / config_snapshot / input_item / ...: no conversation event.


def _handle_response_item(
    payload: dict,
    state: _RolloutState,
    events: list[MemoryEvent],
    path: Path,
    byte_start: int,
    ts,
) -> None:
    item_type = payload.get("type")

    if item_type == "message":
        role_str = payload.get("role", "")
        if role_str in ("developer", "system"):
            return  # agent instructions/boilerplate, not conversation
        try:
            role = Role(role_str)
        except ValueError:
            logger.warning("Unknown message role %r in %s; skipping", role_str, path)
            return
        blocks = _text_blocks(payload.get("content"))
        if not blocks:
            return
        events.append(_make_event(state, path, byte_start, ts, role, blocks))
        return

    if item_type == "reasoning":
        summary = payload.get("summary")
        texts = (
            [p["text"] for p in summary if isinstance(p, dict) and p.get("text")]
            if isinstance(summary, list)
            else []
        )
        if not texts:
            return  # encrypted-only reasoning carries nothing indexable
        blocks = [ContentBlock(block_type=BlockType.THINKING, text="\n".join(texts))]
        events.append(_make_event(state, path, byte_start, ts, Role.ASSISTANT, blocks))
        return

    if item_type in ("function_call", "custom_tool_call", "local_shell_call"):
        blocks = [
            ContentBlock(
                block_type=BlockType.TOOL_USE,
                tool_name=payload.get("name") or item_type,
                tool_id=payload.get("call_id") or payload.get("id") or f"call_{byte_start}",
                tool_input=_parse_tool_input(payload),
            )
        ]
        events.append(_make_event(state, path, byte_start, ts, Role.ASSISTANT, blocks))
        return

    if item_type == "function_call_output":
        output = payload.get("output", "")
        text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
        blocks = [
            ContentBlock(
                block_type=BlockType.TOOL_RESULT,
                tool_id=payload.get("call_id") or f"call_{byte_start}",
                text=truncate_tool_result(text),
            )
        ]
        events.append(_make_event(state, path, byte_start, ts, Role.USER, blocks))
        return
    # web_search_call / item_reference / ...: ignored for now.


def _handle_event_msg(payload: dict, state: _RolloutState) -> None:
    msg_type = payload.get("type")
    if msg_type == "token_count":
        _apply_token_count(payload, state)
        return
    # agent_message / user_message duplicate response_item/message and would
    # double-count the conversation; exec_*/mcp_*/task_*/turn_* are lifecycle
    # noise. All suppressed.


def _apply_token_count(payload: dict, state: _RolloutState) -> None:
    """Attach per-interval usage to the last assistant event seen *this pass*.

    ``token_count`` is cumulative, so the raw totals are differenced against a
    running baseline (a ``last_token_usage`` delta, when present, is trusted
    directly). Events without an in-pass assistant anchor — e.g. the first
    token_count after an incremental resume — are dropped rather than attached
    with an inflated from-zero delta; a full re-scan rebuilds correct totals.
    Negative deltas (cumulative reset after compaction) are clamped to zero.
    """
    info = payload.get("info") if isinstance(payload.get("info"), dict) else payload

    last = info.get("last_token_usage")
    if isinstance(last, dict):
        delta = normalize_codex_usage(last)
    else:
        total = info.get("total_token_usage")
        if not isinstance(total, dict):
            total = info if "input_tokens" in info else None
        if total is None:
            return
        u = normalize_codex_usage(total)
        delta = StandardUsage(
            token_input=u.token_input - state.cum_input,
            token_output=u.token_output - state.cum_output,
            token_cache_read=u.token_cache_read - state.cum_cache_read,
        )
        state.cum_input = u.token_input
        state.cum_output = u.token_output
        state.cum_cache_read = u.token_cache_read

    target = state.last_assistant
    if target is None:
        return
    target.token_input += max(delta.token_input, 0)
    target.token_output += max(delta.token_output, 0)
    target.token_cache_read += max(delta.token_cache_read, 0)


def _make_event(
    state: _RolloutState,
    path: Path,
    byte_start: int,
    ts_raw,
    role: Role,
    blocks: list[ContentBlock],
) -> MemoryEvent:
    session_id = state.session_id or path.stem
    try:
        timestamp = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        logger.warning("Bad timestamp %r at %s:%d; using now()", ts_raw, path, byte_start)
        timestamp = datetime.now(UTC)

    event = MemoryEvent(
        event_id=f"{session_id}:{byte_start}",
        session_id=session_id,
        source=CodexParser.SOURCE_NAME,
        parent_event_id=state.prev_event_id,
        timestamp=timestamp,
        role=role,
        content_blocks=blocks,
        cwd=state.cwd,
        git_branch=state.git_branch,
        model=state.model,
        provider=state.provider,
    )
    # Rollouts are a linear stream (no parent pointers); chain each event to
    # the previous one so event_edges preserves ordering.
    state.prev_event_id = event.event_id
    if role == Role.ASSISTANT:
        state.last_assistant = event
    return event


def _text_blocks(content) -> list[ContentBlock]:
    """Extract TEXT blocks from a message's content (list of parts or string)."""
    if isinstance(content, str):
        return [ContentBlock(block_type=BlockType.TEXT, text=content)] if content else []
    if not isinstance(content, list):
        return []
    return [
        ContentBlock(block_type=BlockType.TEXT, text=part["text"])
        for part in content
        if isinstance(part, dict) and part.get("text")
    ]


def _parse_tool_input(payload: dict) -> dict:
    """Tool input as a dict. ``arguments``/``input`` arrive as a JSON-encoded
    string; ``local_shell_call`` carries an ``action`` object instead."""
    action = payload.get("action")
    if isinstance(action, dict):
        return action
    raw = payload.get("arguments", payload.get("input"))
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"_raw": raw}
        return parsed if isinstance(parsed, dict) else {"_raw": raw}
    return {}


def _extract_summary(path: Path) -> str:
    """First user-message text, truncated. Rollouts have no summary line."""
    for _, line in iter_complete_lines(path, 0):
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict) or raw.get("type") != "response_item":
            continue
        payload = raw.get("payload")
        if not isinstance(payload, dict):
            continue
        if payload.get("type") != "message" or payload.get("role") != "user":
            continue
        for block in _text_blocks(payload.get("content")):
            if block.text:
                return truncate_text(block.text, _SUMMARY_MAX_LEN)
    return "(no summary)"
