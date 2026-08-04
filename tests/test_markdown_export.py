"""Unit tests for the Markdown session exporter (pure render_session_markdown)."""

import json

import pytest

from bagger.exporters.markdown import (
    SUPPORTED_FORMATS,
    render_session,
    render_session_markdown,
)

SESSION = {
    "id": "abc123def456",
    "source": "claude",
    "summary": "Refactor the auth module",
    "project_path": "/home/user/proj",
    "message_count": 3,
    "first_message_at": "2026-08-04T10:00:00",
    "last_message_at": "2026-08-04T10:42:00",
}


def _ev(role, blocks, **extra):
    return {
        "role": role,
        "timestamp": "2026-08-04T10:05:00",
        "content_json": json.dumps(blocks, ensure_ascii=False),
        "content_text": "",
        "model": None,
        "token_input": 0,
        "token_output": 0,
        **extra,
    }


def test_renders_title_and_meta():
    md = render_session_markdown(SESSION, [])
    assert "# Refactor the auth module" in md
    assert "**Source:** claude" in md
    assert "**Project:** /home/user/proj" in md
    assert "**Session ID:** `abc123def456`" in md
    assert "Exported by **bagger**" in md


def test_text_and_tool_use_blocks():
    events = [
        _ev("user", [{"block_type": "text", "text": "Please fix the bug in login.py"}]),
        _ev(
            "assistant",
            [
                {"block_type": "text", "text": "Sure, I'll edit it."},
                {
                    "block_type": "tool_use",
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "login.py", "old_string": "x", "new_string": "y"},
                },
            ],
            token_input=120,
            token_output=40,
        ),
    ]
    md = render_session_markdown(SESSION, events)
    assert "## 👤 User — 2026-08-04 10:05" in md
    assert "## 🤖 Assistant — 2026-08-04 10:05" in md
    assert "Please fix the bug in login.py" in md
    assert "**🔧 Edit** — `login.py`" in md
    assert "```json" in md
    assert '"file_path": "login.py"' in md
    # assistant token footnote
    assert "_tokens: in 120 · out 40_" in md


def test_thinking_rendered_as_blockquote():
    events = [
        _ev(
            "assistant",
            [{"block_type": "thinking", "text": "Let me reason about this step."}],
        )
    ]
    md = render_session_markdown(SESSION, events)
    assert "> 💭 **thinking**" in md
    assert "> Let me reason about this step." in md


def test_tool_result_truncated():
    big = "x" * 5000
    events = [_ev("assistant", [{"block_type": "tool_result", "tool_name": "Bash", "text": big}])]
    md = render_session_markdown(SESSION, events, max_tool_result_chars=2000)
    assert "📎 **result** (Bash)" in md
    assert "more characters truncated" in md
    assert "xxxx" in md


def test_falls_back_to_content_text_when_json_broken():
    ev = {
        "role": "user",
        "timestamp": "2026-08-04T10:05:00",
        "content_json": "not-json",
        "content_text": "Plain fallback text",
    }
    md = render_session_markdown(SESSION, [ev])
    assert "Plain fallback text" in md


def test_cost_footnote_when_present():
    events = [
        _ev(
            "assistant",
            [{"block_type": "text", "text": "Done."}],
            token_input=10,
            token_output=5,
            cost_usd=0.0123,
        )
    ]
    md = render_session_markdown(SESSION, events)
    assert "_cost $0.0123_" in md


def test_supported_formats_and_dispatch():
    assert "markdown" in SUPPORTED_FORMATS
    with pytest.raises(ValueError):
        render_session(SESSION, [], fmt="pdf")
    md = render_session(SESSION, [], fmt="markdown")
    assert "# Refactor the auth module" in md
