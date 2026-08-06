"""Tests for ParserRegistry plugin-style auto-discovery (P2-②)."""

from bagger.parsers import ParserRegistry
from bagger.parsers.base import _iter_parser_classes


def test_load_builtin_registers_known_parsers():
    # Discovery is process-global and other tests legitimately mutate the
    # registry, so reset to a known state and verify load_builtin finds
    # exactly claude + codex.
    ParserRegistry.clear()
    ParserRegistry.load_builtin(force=True)
    assert ParserRegistry.list_all() == ["claude", "codex"]


def test_load_builtin_is_idempotent():
    ParserRegistry.clear()
    ParserRegistry.load_builtin(force=True)
    before = ParserRegistry.list_all()
    ParserRegistry.load_builtin()  # no-op (already loaded)
    assert ParserRegistry.list_all() == before


def test_discovery_ignores_abstract_and_imported_parsers():
    # The abstract Parser itself and any Parser imported for type hints must
    # not be picked up; only concrete plugins defined in the package surface.
    found = {klass.__name__ for klass in _iter_parser_classes()}
    assert "Parser" not in found  # abstract base excluded
    assert "ParserRegistry" not in found
    assert found == {"ClaudeParser", "CodexParser"}


def test_discovery_picks_up_new_plugin_module(tmp_path, monkeypatch):
    # Prove the "drop a module -> auto-registered" contract: extend the
    # package __path__ with a temp dir holding a brand-new parser and re-scan.
    probe = tmp_path / "discprobe.py"
    probe.write_text(
        "from bagger.parsers.base import Parser, StandardUsage\n"
        "from bagger.models.event import MemoryEvent\n"
        "\n"
        "class DiscProbeParser(Parser):\n"
        "    @property\n"
        "    def source_name(self):\n"
        "        return 'discprobe'\n"
        "    def discover_sessions(self):\n"
        "        return []\n"
        "    def parse(self, path):\n"
        "        return []\n"
        "    def parse_incremental(self, path, offset):\n"
        "        return []\n"
        "    def extract_summary(self, path):\n"
        "        return ''\n"
        "    def normalize_usage(self, raw_usage, raw_model=None):\n"
        "        return StandardUsage()\n",
        encoding="utf-8",
    )
    import bagger.parsers as pkg

    monkeypatch.setattr(pkg, "__path__", [*pkg.__path__, str(tmp_path)])
    try:
        ParserRegistry.clear()
        ParserRegistry.load_builtin(force=True)
        assert "discprobe" in ParserRegistry.list_all()
    finally:
        # Restore the real registry. Delete the probe file first so the
        # re-scan doesn't leave the discprobe source registered globally.
        probe.unlink(missing_ok=True)
        ParserRegistry.clear()
        ParserRegistry.load_builtin()
