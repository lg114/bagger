"""Tests for search-quality improvements: CJK single-char recall + tool_result truncation."""

import pytest

from bagger.models.event import BlockType, Role
from bagger.parsers.claude import TOOL_RESULT_MAX_CHARS, _parse_content, _truncate_tool_result


def test_tokenize_for_fts_adds_cjk_char_tokens():
    """A single-hanzi query must recall a multi-char word containing it.

    jieba only emits *words*, so without the per-character fallback a query like
    "数" would never match "数据库". The index must contain the individual chars.
    """
    pytest.importorskip("jieba")
    from bagger.storage.sqlite import _tokenize_for_fts

    out = _tokenize_for_fts("数据库连接测试")
    tokens = out.split()
    # Every CJK character appears as its own token.
    assert "数" in tokens
    assert "据" in tokens
    assert "库" in tokens
    assert "连" in tokens
    assert "接" in tokens
    assert "测" in tokens
    assert "试" in tokens
    # Plus at least the jieba word tokens (more tokens than just the 7 chars).
    assert len(tokens) > 7


def test_parse_content_truncates_oversized_tool_result():
    big = "x" * (TOOL_RESULT_MAX_CHARS + 5000)
    blocks = _parse_content(Role.USER, [{"type": "tool_result", "content": big}])
    tr = [b for b in blocks if b.block_type == BlockType.TOOL_RESULT]
    assert len(tr) == 1
    # Stored text is bounded (marker adds a little, so allow slack).
    assert len(tr[0].text) <= TOOL_RESULT_MAX_CHARS + 64
    assert "truncated" in tr[0].text


def test_parse_content_keeps_small_tool_result():
    small = "just a small result"
    blocks = _parse_content(Role.USER, [{"type": "tool_result", "content": small}])
    tr = [b for b in blocks if b.block_type == BlockType.TOOL_RESULT]
    assert len(tr) == 1
    assert tr[0].text == small
    assert "truncated" not in tr[0].text


def test_truncate_tool_result_helper():
    assert _truncate_tool_result("short") == "short"
    # Clearly oversized (suffix adds a little overhead, so use well past the limit).
    long = "y" * (TOOL_RESULT_MAX_CHARS + 5000)
    truncated = _truncate_tool_result(long)
    assert truncated.endswith("[tool_result truncated]")
    assert len(truncated) < len(long)
    # Content portion is capped exactly at the limit.
    assert len(truncated) - len("\n...[tool_result truncated]") == TOOL_RESULT_MAX_CHARS
