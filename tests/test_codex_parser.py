"""Tests for the Codex rollout JSONL parser."""

import gc
import shutil
import tempfile
from pathlib import Path

from bagger.models.event import BlockType, Role
from bagger.parsers.codex import (
    CodexParser,
    normalize_codex_usage,
)
from bagger.services.sync import SyncService
from bagger.storage.sqlite import SqliteStorage

FIXTURE = Path(__file__).parent / "fixtures" / "codex_rollout_sample.jsonl"


# ── Full parse ─────────────────────────────────────────────


def test_parse_returns_five_conversation_events():
    """developer/system messages, duplicate event_msg chatter, compacted
    markers and broken lines are all filtered out."""
    events = CodexParser().parse(FIXTURE)
    assert len(events) == 5
    assert [e.role for e in events] == [
        Role.USER,  # user message
        Role.ASSISTANT,  # reasoning
        Role.ASSISTANT,  # function_call
        Role.USER,  # function_call_output
        Role.ASSISTANT,  # assistant message
    ]
    all_text = " ".join(b.text or "" for e in events for b in e.content_blocks)
    assert "You are Codex" not in all_text  # developer boilerplate dropped
    assert "应被抑制" not in all_text  # duplicate agent_message suppressed


def test_user_message_text_block():
    events = CodexParser().parse(FIXTURE)
    user = events[0]
    assert user.content_blocks[0].block_type == BlockType.TEXT
    assert "flaky" in user.content_blocks[0].text


def test_reasoning_becomes_thinking_block():
    events = CodexParser().parse(FIXTURE)
    thinking = [b for b in events[1].content_blocks if b.block_type == BlockType.THINKING]
    assert len(thinking) == 1
    assert "复现" in thinking[0].text


def test_tool_call_pairing_by_call_id():
    events = CodexParser().parse(FIXTURE)
    call = events[2].content_blocks[0]
    result = events[3].content_blocks[0]
    assert call.block_type == BlockType.TOOL_USE
    assert call.tool_name == "exec_command"
    assert call.tool_id == "call_1"
    assert call.tool_input == {"cmd": "pytest -x"}  # arguments JSON-string decoded
    assert result.block_type == BlockType.TOOL_RESULT
    assert result.tool_id == "call_1"
    assert "1 failed" in result.text


def test_cumulative_token_count_is_differenced():
    """token_count totals are cumulative; each assistant event must receive
    only the delta since the previous report."""
    events = CodexParser().parse(FIXTURE)
    func_call = events[2]
    assert func_call.token_input == 1000
    assert func_call.token_output == 120
    assert func_call.token_cache_read == 400
    assistant_msg = events[4]
    assert assistant_msg.token_input == 500  # 1500 - 1000
    assert assistant_msg.token_output == 180  # 300 - 120
    assert assistant_msg.token_cache_read == 200  # 600 - 400
    assert assistant_msg.cost_usd is None  # never fabricated


def test_event_metadata_from_meta_and_turn_context():
    events = CodexParser().parse(FIXTURE)
    for e in events:
        assert e.session_id == "codex-sess-001"
        assert e.source == "codex"
        assert e.cwd == "/home/gc/proj"
        assert e.git_branch == "main"
        assert e.provider == "openai"  # session_meta.model_provider, no heuristic
        assert e.model == "gpt-5.6"  # turn_context


def test_linear_parent_chain():
    from itertools import pairwise

    events = CodexParser().parse(FIXTURE)
    assert events[0].parent_event_id is None
    for prev, cur in pairwise(events):
        assert cur.parent_event_id == prev.event_id


# ── Incremental parse ──────────────────────────────────────


def _byte_offset_of(marker: bytes) -> int:
    data = FIXTURE.read_bytes()
    return data.rfind(b"\n", 0, data.index(marker)) + 1


def test_incremental_matches_full_parse_suffix():
    """Resuming from a byte offset must yield the same event ids as the full
    parse (ids are synthesized from byte offsets, seeded with session_meta)."""
    offset = _byte_offset_of(b'"type":"function_call"')
    full = CodexParser().parse(FIXTURE)
    incr = CodexParser().parse_incremental(FIXTURE, offset)
    assert [e.event_id for e in incr] == [e.event_id for e in full[2:]]
    # Token deltas land identically: the first in-pass token_count has the
    # same zero baseline as the full parse had at that point.
    assert [e.token_input for e in incr] == [e.token_input for e in full[2:]]


def test_incremental_event_ids_use_session_meta_id_not_filename():
    """The regression case: without session_meta seeding, resumed events would
    be keyed on the rollout filename stem and orphan the Session row."""
    offset = _byte_offset_of(b'"type":"function_call"')
    incr = CodexParser().parse_incremental(FIXTURE, offset)
    assert all(e.session_id == "codex-sess-001" for e in incr)
    assert all(e.event_id.startswith("codex-sess-001:") for e in incr)


# ── Discovery / session id / summary ───────────────────────


def test_discover_sessions_filters_name_and_validates_meta():
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        day = home / "sessions" / "2026" / "07" / "01"
        day.mkdir(parents=True)
        valid = day / "rollout-2026-07-01T09-00-00-aaa-bbb.jsonl"
        shutil.copy(FIXTURE, valid)
        (day / "other.jsonl").write_text("{}\n", encoding="utf-8")  # wrong name
        (day / "rollout-broken.jsonl").write_text("garbage\n", encoding="utf-8")  # no meta

        files = CodexParser(codex_home=home).discover_sessions()
        assert [p.name for p in files] == [valid.name]


def test_session_id_for_prefers_session_meta():
    assert CodexParser().session_id_for(FIXTURE) == "codex-sess-001"


def test_session_id_for_filename_fallback():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "rollout-2026-07-01T09-00-00-dead-beef-1234.jsonl"
        p.write_text("not json\n", encoding="utf-8")
        assert CodexParser().session_id_for(p) == "dead-beef-1234"


def test_extract_summary_first_user_message():
    assert "flaky" in CodexParser().extract_summary(FIXTURE)


# ── Usage normalization ────────────────────────────────────


def test_normalize_codex_usage_protocol_shape():
    u = normalize_codex_usage({"input_tokens": 100, "output_tokens": 50, "cached_input_tokens": 30})
    assert u.token_input == 100
    assert u.token_output == 50
    assert u.token_cache_read == 30
    assert u.token_cache_write == 0
    assert u.cost_usd is None


def test_normalize_codex_usage_responses_api_shape():
    u = normalize_codex_usage(
        {"input_tokens": 100, "output_tokens": 50, "input_tokens_details": {"cached_tokens": 22}}
    )
    assert u.token_cache_read == 22


# ── Sync integration: the session_id_for hook ──────────────


def test_sync_file_keys_session_on_meta_id_not_filename():
    """End-to-end: SyncService must key the Session row and watch offset on
    ``session_meta.id``, not on the rollout filename stem."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmp = Path(tmpdir)
        day = tmp / "codex" / "sessions" / "2026" / "07" / "01"
        day.mkdir(parents=True)
        path = day / "rollout-2026-07-01T09-00-00-whatever.jsonl"
        shutil.copy(FIXTURE, path)

        storage = SqliteStorage(tmp / "test.db")
        storage.connect()
        sync = SyncService(
            storage,
            CodexParser(codex_home=tmp / "codex"),
            jsonl_path=tmp / "events.jsonl",
        )
        try:
            offsets: dict[str, int] = {}
            result = sync.sync_file(path, offsets)

            assert result.new_count == 5
            assert storage.get_event_count("codex-sess-001", "codex") == 5
            assert storage.get_session("codex-sess-001", "codex") is not None
            assert "codex:codex-sess-001" in offsets
        finally:
            sync.close()
            storage.close()
            gc.collect()
