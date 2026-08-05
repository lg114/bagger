"""Tests for the jieba / CJK search guard.

When jieba is unavailable and the indexed data contains Chinese/Japanese/
Korean text, bagger must surface a warning instead of silently producing an
unsearchable FTS index (FTS5's unicode61 tokenizer does not split CJK chars).
"""

import logging
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from bagger.cjk import JIEBA_CJK_WARNING
from bagger.models.event import BlockType, ContentBlock, MemoryEvent, Role
from bagger.parsers.base import Parser, StandardUsage
from bagger.services.scanner import check_jieba_cjk_incoming
from bagger.storage.sqlite import (
    SqliteStorage,
    check_jieba_cjk_coverage,
)


def _cjk_event() -> MemoryEvent:
    return MemoryEvent(
        event_id="e1",
        session_id="s1",
        source="claude",
        timestamp=datetime(2026, 1, 1),
        role=Role.USER,
        content_blocks=[ContentBlock(block_type=BlockType.TEXT, text="你了解这个项目吗")],
    )


def _english_event() -> MemoryEvent:
    return MemoryEvent(
        event_id="e1",
        session_id="s1",
        source="claude",
        timestamp=datetime(2026, 1, 1),
        role=Role.USER,
        content_blocks=[ContentBlock(block_type=BlockType.TEXT, text="Fix the token bug")],
    )


def _storage(tmp_path: Path) -> SqliteStorage:
    storage = SqliteStorage(tmp_path / "test.db")
    storage.connect()
    return storage


# ── rebuild_fts_index path (storage) ──────────────────────────


def test_rebuild_warns_when_jieba_missing_and_cjk(tmp_path, caplog):
    storage = _storage(tmp_path)
    storage.insert_event(_cjk_event())
    with (
        patch("bagger.storage.sqlite.jieba_available", return_value=False),
        caplog.at_level(logging.WARNING),
    ):
        storage.rebuild_fts_index()
    assert JIEBA_CJK_WARNING in caplog.text


def test_rebuild_no_warn_when_jieba_present(tmp_path, caplog):
    storage = _storage(tmp_path)
    storage.insert_event(_cjk_event())
    with (
        patch("bagger.storage.sqlite.jieba_available", return_value=True),
        caplog.at_level(logging.WARNING),
    ):
        storage.rebuild_fts_index()
    assert JIEBA_CJK_WARNING not in caplog.text


def test_rebuild_no_warn_when_english_only(tmp_path, caplog):
    storage = _storage(tmp_path)
    storage.insert_event(_english_event())
    with (
        patch("bagger.storage.sqlite.jieba_available", return_value=False),
        caplog.at_level(logging.WARNING),
    ):
        storage.rebuild_fts_index()
    assert JIEBA_CJK_WARNING not in caplog.text


def test_check_jieba_cjk_coverage_direct(tmp_path):
    storage = _storage(tmp_path)
    storage.insert_event(_cjk_event())
    with patch("bagger.storage.sqlite.jieba_available", return_value=False):
        assert check_jieba_cjk_coverage(storage._conn) == JIEBA_CJK_WARNING
    with patch("bagger.storage.sqlite.jieba_available", return_value=True):
        assert check_jieba_cjk_coverage(storage._conn) is None


# ── scan path (scanner) ───────────────────────────────────────


class _FakeParser(Parser):
    source_name = "fake"

    def discover_sessions(self) -> list[Path]:
        return [Path("/dummy/transcript.jsonl")]

    def parse(self, path: Path) -> list[MemoryEvent]:
        return [_cjk_event()]

    def parse_incremental(self, path: Path, offset: int) -> list[MemoryEvent]:
        return []

    def extract_summary(self, path: Path) -> str:
        return "summary"

    def normalize_usage(self, raw_usage: dict, raw_model: str | None = None) -> StandardUsage:
        return StandardUsage()


class _FakeEnglishParser(_FakeParser):
    def parse(self, path: Path) -> list[MemoryEvent]:
        return [_english_event()]


def test_scanner_warns_when_jieba_missing_and_cjk():
    with patch("bagger.services.scanner.jieba_available", return_value=False):
        assert check_jieba_cjk_incoming(_FakeParser()) == JIEBA_CJK_WARNING


def test_scanner_no_warn_when_jieba_present():
    with patch("bagger.services.scanner.jieba_available", return_value=True):
        assert check_jieba_cjk_incoming(_FakeParser()) is None


def test_scanner_no_warn_when_english_only():
    with patch("bagger.services.scanner.jieba_available", return_value=False):
        assert check_jieba_cjk_incoming(_FakeEnglishParser()) is None
