"""Terminal-based conversation replay."""

import json

from bagger.storage.sqlite import SqliteStorage

try:
    import click

    _HAS_COLOR = True
except ImportError:
    _HAS_COLOR = False


def _style(text: str, **kwargs) -> str:
    """Apply click styling if available, else return plain text."""
    return click.style(text, **kwargs) if _HAS_COLOR else text


def replay_session(
    storage: SqliteStorage,
    session_id: str,
) -> str:
    """Replay a full session as formatted terminal output."""
    events = storage.get_session_events(session_id)
    if not events:
        return f"No events found for session {session_id}"

    lines: list[str] = []
    session_info = storage.get_session(session_id)
    if session_info:
        lines.append(f"Session:  {session_info['summary']}")
        lines.append(f"Messages: {session_info['message_count']}")
        lines.append("─" * 60)
    lines.append("")

    for ev in events:
        ts = ev["timestamp"][:19].replace("T", " ")
        role = ev["role"]

        # Role header
        if role == "user":
            lines.append(_style(f"[{ts}]  User:", fg="cyan", bold=True))
        else:
            lines.append(_style(f"[{ts}]  Assistant:", fg="green", bold=True))

        # Content blocks
        blocks = json.loads(ev["content_json"])
        for block in blocks:
            bt = block.get("block_type", "")
            text = block.get("text", "")
            tool_name = block.get("tool_name", "")

            if bt == "thinking":
                lines.append(_style(f"  [thinking] {text}", dim=True))
            elif bt == "text":
                lines.extend(f"  {l}" for l in text.split("\n"))
            elif bt == "tool_use":
                lines.append(_style(f"  tool_use: {tool_name}", fg="yellow"))
            elif bt == "tool_result":
                lines.append(_style(f"  result: {text[:120]}", dim=True))

        # Tokens
        if ev.get("token_input") or ev.get("token_output"):
            info = f"  [tokens: in={ev['token_input']} out={ev['token_output']}]"
            lines.append(_style(info, dim=True))

        lines.append("")

    return "\n".join(lines)
