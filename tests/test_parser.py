"""Tests for Claude Code JSONL parser."""

import json
import tempfile
from pathlib import Path

from bagger.models.event import BlockType, Role
from bagger.parser.claude import (
    _resolve_provider,
    extract_summary,
    normalize_claude_usage,
    parse_jsonl,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_session.jsonl"


def test_parse_jsonl_returns_events():
    events = parse_jsonl(FIXTURE)
    assert len(events) == 6  # 3 user + 3 assistant

    roles = [e.role for e in events]
    assert roles[0] == Role.USER
    assert roles[1] == Role.ASSISTANT
    assert roles[2] == Role.USER  # tool_result
    assert roles[3] == Role.ASSISTANT
    assert roles[4] == Role.USER  # tool_result
    assert roles[5] == Role.ASSISTANT


def test_user_message_has_text_block():
    events = parse_jsonl(FIXTURE)
    user_msg = events[0]
    assert user_msg.role == Role.USER
    assert len(user_msg.content_blocks) == 1
    assert user_msg.content_blocks[0].block_type == BlockType.TEXT
    assert "登录" in user_msg.content_blocks[0].text


def test_assistant_response_has_text_and_tool_use():
    events = parse_jsonl(FIXTURE)
    assistant = events[1]
    assert assistant.role == Role.ASSISTANT
    block_types = [b.block_type for b in assistant.content_blocks]
    assert BlockType.TEXT in block_types
    assert BlockType.TOOL_USE in block_types


def test_tool_result_is_parsed():
    events = parse_jsonl(FIXTURE)
    tool_result = events[2]
    assert tool_result.role == Role.USER
    assert tool_result.content_blocks[0].block_type == BlockType.TOOL_RESULT
    assert "import jwt" in tool_result.content_blocks[0].text


def test_thinking_is_parsed():
    events = parse_jsonl(FIXTURE)
    thinking_event = events[3]
    thinking_blocks = [
        b for b in thinking_event.content_blocks if b.block_type == BlockType.THINKING
    ]
    assert len(thinking_blocks) == 1
    assert "5 分钟" in thinking_blocks[0].text


def test_model_and_usage_are_extracted():
    events = parse_jsonl(FIXTURE)
    assistant = events[1]
    assert assistant.model == "claude-sonnet-4-20250514"
    assert assistant.token_input == 150
    assert assistant.token_output == 80


def test_session_metadata():
    events = parse_jsonl(FIXTURE)
    user = events[0]
    assert user.session_id == "abc-123-session"
    assert user.cwd == "/home/gc/project"
    assert user.git_branch == "main"


def test_extract_summary():
    summary = extract_summary(FIXTURE)
    assert "Fix login token expiration" in summary


def test_file_history_snapshot_skipped():
    events = parse_jsonl(FIXTURE)
    # 4 real events, file-history-snapshot should be skipped
    assert len(events) == 6  # no file-history-snapshot


def test_normalize_claude_usage_captures_cache_cost_tier():
    u = normalize_claude_usage(
        {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 200,
            "cache_creation_input_tokens": 30,
            "service_tier": "standard",
            "cost_usd": 0.0123,
        },
        "claude-sonnet-4-20250514",
    )
    assert u.token_input == 100
    assert u.token_output == 50
    assert u.token_cache_read == 200
    assert u.token_cache_write == 30
    assert u.service_tier == "standard"
    assert u.cost_usd == 0.0123
    assert u.currency == "USD"


def test_normalize_claude_usage_cost_zero_is_none():
    # cost_usd <= 0 (or absent) must be stored as None, never fabricated
    u = normalize_claude_usage({"input_tokens": 1, "output_tokens": 1, "cost_usd": 0}, "mimo-x")
    assert u.cost_usd is None


def test_resolve_provider_heuristics():
    assert _resolve_provider("claude-opus-4") == "anthropic"
    assert _resolve_provider("anthropic-sonnet") == "anthropic"
    assert _resolve_provider("xiaomi/mimo") == "xiaomi"
    assert _resolve_provider("mimo-x") == "xiaomi"
    assert _resolve_provider("gpt-4o") == "openai"
    assert _resolve_provider("deepseek-chat") == "deepseek"
    assert _resolve_provider(None) is None
    assert _resolve_provider("something-unknown") is None


def test_parse_entry_stores_usage_and_provider():
    raw = {
        "type": "assistant",
        "uuid": "u-1",
        "sessionId": "s-1",
        "timestamp": "2026-01-01T00:00:00.000Z",
        "message": {
            "role": "assistant",
            "model": "claude-sonnet-4-20250514",
            "content": [{"type": "text", "text": "hi"}],
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_input_tokens": 200,
                "cache_creation_input_tokens": 30,
                "service_tier": "standard",
                "cost_usd": 0.0123,
            },
        },
    }
    tmp = Path(tempfile.mktemp(suffix=".jsonl"))
    tmp.write_text(json.dumps(raw), encoding="utf-8")
    try:
        events = parse_jsonl(tmp)
    finally:
        tmp.unlink()

    assert len(events) == 1
    e = events[0]
    assert e.token_cache_read == 200
    assert e.token_cache_write == 30
    assert e.service_tier == "standard"
    assert e.cost_usd == 0.0123
    assert e.provider == "anthropic"
