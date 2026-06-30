"""Terminal-based conversation replay."""

import json
from typing import Optional

from bagger.storage.sqlite import SqliteStorage


try:
    import click
    _HAS_COLOR = True
except ImportError:
    _HAS_COLOR = False


def replay_session(
    storage: SqliteStorage,
    session_id: str,
    use_color: bool = True,
) -> str:
    """Replay a full session as formatted terminal output.

    Returns the formatted string.
    """
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
        role_label = "User" if ev["role"] == "user" else "Assistant"

        if use_color and _HAS_COLOR:
            if ev["role"] == "user":
                role_line = click.style(f"[{ts}]  User:", fg="cyan", bold=True)
            else:
                role_line = click.style(f"[{ts}]  Assistant:", fg="green", bold=True)
        else:
            role_line = f"[{ts}]  {role_label}:"

        lines.append(role_line)

        content_blocks = json.loads(ev["content_json"])
        for block in content_blocks:
            bt = block.get("block_type", "")
            if bt in ("text", "thinking"):
                text = block.get("text", "")
                if bt == "thinking":
                    if use_color and _HAS_COLOR:
                        lines.append(
                            "  " + click.style(f"[thinking] {text}", dim=True)
                        )
                    else:
                        lines.append(f"  [thinking] {text}")
                else:
                    for line in text.split("\n"):
                        lines.append(f"  {line}")
            elif bt == "tool_use":
                if use_color and _HAS_COLOR:
                    lines.append(
                        "  "
                        + click.style(
                            f"tool_use: {block.get('tool_name', '')}",
                            fg="yellow",
                        )
                    )
                else:
                    lines.append(
                        f"  tool_use: {block.get('tool_name', '')}"
                    )
            elif bt == "tool_result":
                text = block.get("text", "")
                if use_color and _HAS_COLOR:
                    lines.append(
                        "  " + click.style(f"result: {text[:120]}", dim=True)
                    )
                else:
                    lines.append(f"  result: {text[:120]}")

        token_info = ""
        if ev.get("token_input") or ev.get("token_output"):
            token_info = (
                f"  [tokens: in={ev['token_input']} out={ev['token_output']}]"
            )
            if use_color and _HAS_COLOR:
                token_info = click.style(token_info, dim=True)
        if token_info:
            lines.append(token_info)

        lines.append("")

    return "\n".join(lines)
