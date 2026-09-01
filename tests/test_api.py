"""Tests for the REST API endpoints."""

import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from bagger.api.app import create_app
from bagger.config import Settings
from bagger.models.event import BlockType, ContentBlock, MemoryEvent, Role, Session
from bagger.storage.sqlite import SqliteStorage

# ---- Helpers ----


def _make_event(
    event_id="evt-001",
    session_id="sess-1",
    role=Role.USER,
    text="Hello world",
    parent_event_id=None,
    source="claude",
) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        session_id=session_id,
        parent_event_id=parent_event_id,
        timestamp=datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC),
        role=role,
        content_blocks=[ContentBlock(block_type=BlockType.TEXT, text=text)],
        token_input=10,
        token_output=20,
        source=source,
    )


def _override_db(tmpdir: Path) -> SqliteStorage:
    """Set up a test database and override the default settings."""
    import bagger.config as config

    # create_storage() reads from bagger.config.settings; patch it so
    # get_storage() opens the temp DB instead of the user's real DB.
    config.settings = Settings(bagger_dir=tmpdir)
    db_path = config.settings.db_path

    storage = SqliteStorage(db_path)
    storage.connect()
    return storage


# ---- Tests ----


def test_health_check():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)

        # Insert some data so health check has something to report
        storage.insert_event(_make_event())
        storage.upsert_session(Session(session_id="sess-1", summary="Test"))
        storage.close()

        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)

        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["sessions_count"] == 1
        assert data["events_count"] == 1
        assert data["fts_enabled"] is True


def test_health_version_matches_package_metadata():
    """/api/health version must match bagger.__version__ (single source of truth)."""
    from bagger import __version__

    with tempfile.TemporaryDirectory() as tmpdir:
        _override_db(Path(tmpdir)).close()

        from fastapi.testclient import TestClient

        client = TestClient(create_app())
        response = client.get("/api/health")

        assert response.status_code == 200
        assert response.json()["version"] == __version__


def test_list_sessions_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)
        storage.close()

        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)

        response = client.get("/api/sessions")
        assert response.status_code == 200
        data = response.json()
        assert data["meta"]["total"] == 0
        assert data["data"] == []


def test_list_sessions_paginated():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)

        for i in range(5):
            storage.upsert_session(
                Session(session_id=f"sess-p-{i}", summary=f"Session {i}", message_count=i + 1)
            )
        storage.close()

        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)

        response = client.get("/api/sessions?page=1&per_page=3")
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 3
        assert data["meta"]["total"] == 5
        assert data["meta"]["pages"] == 2


def test_list_sessions_filters_by_source():
    """?source= scopes the list and its total to one AI tool (§5.5 / (b))."""
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)
        storage.upsert_session(Session(session_id="c1", summary="Claude", source="claude"))
        storage.upsert_session(Session(session_id="g1", summary="ChatGPT", source="chatgpt"))
        storage.close()

        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)

        # No filter -> both sources.
        all_resp = client.get("/api/sessions")
        assert all_resp.status_code == 200
        assert all_resp.json()["meta"]["total"] == 2

        # source=chatgpt -> only the chatgpt session (and total reflects it).
        resp = client.get("/api/sessions?source=chatgpt")
        assert resp.status_code == 200
        data = resp.json()
        assert data["meta"]["total"] == 1
        assert data["data"][0]["id"] == "g1"
        assert data["data"][0]["source"] == "chatgpt"

        # source=claude -> only the claude session.
        resp = client.get("/api/sessions?source=claude")
        assert resp.json()["meta"]["total"] == 1
        assert resp.json()["data"][0]["id"] == "c1"


def test_get_session_not_found():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)
        storage.close()

        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)

        response = client.get("/api/sessions/nonexistent")
        assert response.status_code == 404


def test_get_session_found():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)
        storage.upsert_session(
            Session(
                session_id="abc-def-123",
                summary="Found session",
                project_path="/tmp/test",
                message_count=3,
            )
        )
        storage.close()

        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)

        response = client.get("/api/sessions/abc-def-123")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"] == "Found session"
        assert data["message_count"] == 3


def test_get_session_events():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)

        storage.upsert_session(Session(session_id="sess-e", summary="Event test"))
        storage.insert_events(
            [
                _make_event(
                    event_id="e1", session_id="sess-e", role=Role.USER, text="First message"
                ),
                _make_event(
                    event_id="e2", session_id="sess-e", role=Role.ASSISTANT, text="Assistant reply"
                ),
            ]
        )
        storage.close()

        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)

        response = client.get("/api/sessions/sess-e/events")
        assert response.status_code == 200
        data = response.json()
        assert data["meta"]["total"] == 2
        assert len(data["data"]) == 2
        # Events should have content_blocks parsed from JSON
        assert "content_blocks" in data["data"][0]
        assert len(data["data"][0]["content_blocks"]) == 1
        assert data["data"][0]["content_blocks"][0]["text"] == "First message"


def test_export_session_markdown():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)

        storage.upsert_session(Session(session_id="sess-x", summary="Export me", source="claude"))
        storage.insert_events(
            [
                _make_event(
                    event_id="e1", session_id="sess-x", role=Role.USER, text="What is 2+2?"
                ),
                _make_event(
                    event_id="e2",
                    session_id="sess-x",
                    role=Role.ASSISTANT,
                    text="4.",
                    source="claude",
                ),
            ]
        )
        storage.close()

        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)

        # Prefix match works like other session routes.
        response = client.get("/api/sessions/sess-x/export")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/markdown")
        assert "attachment" in response.headers["content-disposition"]
        body = response.text
        assert "# Export me" in body
        assert "What is 2+2?" in body
        assert "🤖 Assistant" in body


def test_export_session_scopes_by_source():
    """Two tools sharing a session ID must export the correct conversation.

    Regression: the export route ignored ``source`` and could export the
    wrong tool's session when Claude and Codex collide on the same ID.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)

        # Same session_id, different source → different conversations.
        storage.upsert_session(Session(session_id="dup", summary="Claude one", source="claude"))
        storage.upsert_session(Session(session_id="dup", summary="Codex two", source="codex"))
        storage.insert_events(
            [
                _make_event(
                    event_id="c1",
                    session_id="dup",
                    role=Role.USER,
                    text="claude question",
                    source="claude",
                ),
                _make_event(
                    event_id="x1",
                    session_id="dup",
                    role=Role.USER,
                    text="codex question",
                    source="codex",
                ),
            ]
        )
        storage.close()

        from fastapi.testclient import TestClient

        client = TestClient(create_app())

        # Without source the backend falls back to un-scoped lookup (legacy).
        unscoped = client.get("/api/sessions/dup/export")
        assert unscoped.status_code == 200

        # With source=claude we must get the Claude conversation only.
        claude = client.get("/api/sessions/dup/export?source=claude")
        assert claude.status_code == 200
        assert "Claude one" in claude.text
        assert "claude question" in claude.text
        assert "codex question" not in claude.text

        # With source=codex we must get the Codex conversation only.
        codex = client.get("/api/sessions/dup/export?source=codex")
        assert codex.status_code == 200
        assert "Codex two" in codex.text
        assert "codex question" in codex.text
        assert "claude question" not in codex.text


def test_sources_endpoint_returns_all_distinct_sources():
    """/api/sources is a true facet: every source in the store, not just page 1."""
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)
        # Many sessions per source so neither fits on a single page of 50.
        for i in range(60):
            storage.upsert_session(Session(session_id=f"c{i}", summary=f"C{i}", source="claude"))
        for i in range(60):
            storage.upsert_session(Session(session_id=f"x{i}", summary=f"X{i}", source="codex"))
        storage.close()

        from fastapi.testclient import TestClient

        client = TestClient(create_app())
        resp = client.get("/api/sources")
        assert resp.status_code == 200
        assert set(resp.json()["sources"]) == {"claude", "codex"}


def test_sources_endpoint_scopes_by_project():
    """/api/sources?project=... narrows the facet to that project's sources."""
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)
        storage.upsert_session(
            Session(session_id="a", summary="A", source="claude", project_path="/p1")
        )
        storage.upsert_session(
            Session(session_id="b", summary="B", source="codex", project_path="/p2")
        )
        storage.close()

        from fastapi.testclient import TestClient

        client = TestClient(create_app())
        p1 = client.get("/api/sources?project=" + "/p1").json()["sources"]
        assert p1 == ["claude"]
        p2 = client.get("/api/sources?project=" + "/p2").json()["sources"]
        assert p2 == ["codex"]


# ── Long-session E2E (1000+ events) ──────────────────────


def test_long_session_paginates_all_events():
    """A 1000+ event session must be fully reachable across paginated pages.

    Real Claude/Codex sessions routinely exceed 1000 events; the UI streams
    them in pages instead of loading everything at once. This locks in the
    end-to-end contract: every event is retrievable, in order, with no gaps
    or duplication — the exact failure mode that used to clip long sessions at
    page 1.
    """
    import math
    from datetime import timedelta

    N = 1200
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)
        sid = "long-sess"
        base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        events = [
            MemoryEvent(
                event_id=f"e{i:05d}",
                session_id=sid,
                timestamp=base + timedelta(seconds=i),
                role=Role.USER,
                content_blocks=[ContentBlock(block_type=BlockType.TEXT, text=f"event {i}")],
                source="claude",
            )
            for i in range(N)
        ]
        storage.insert_events(events)
        storage.upsert_session(
            Session(session_id=sid, summary="Long session", message_count=N, source="claude")
        )
        storage.close()

        from fastapi.testclient import TestClient

        client = TestClient(create_app())

        # Detail reports the true (large) message count.
        detail = client.get(f"/api/sessions/{sid}", params={"source": "claude"}).json()
        assert detail["message_count"] == N

        # Walk every page at per_page=100 → 12 pages for 1200 events.
        per_page = 100
        seen: list[str] = []
        page = 1
        while True:
            resp = client.get(
                f"/api/sessions/{sid}/events",
                params={"source": "claude", "page": page, "per_page": per_page},
            )
            assert resp.status_code == 200
            body = resp.json()
            meta = body["meta"]
            assert meta["page"] == page
            assert meta["per_page"] == per_page
            assert meta["total"] == N
            assert meta["pages"] == math.ceil(N / per_page)
            rows = body["data"]
            if not rows:
                break
            seen.extend(r["event_id"] for r in rows)
            if meta["page"] >= meta["pages"]:
                break
            page += 1

        # All 1200 events retrieved, exactly once, in timestamp order.
        assert len(seen) == N
        assert len(set(seen)) == N
        assert seen == [f"e{i:05d}" for i in range(N)]


# ── Multi-source same-id: detail / export / search ───────


def test_multisource_same_id_detail_export_search():
    """A shared session id across tools must resolve per-source for detail,
    export, AND search — never leak the wrong tool's data.

    This is the consolidated regression for the multi-tool ambiguity fix:
    claude and codex can emit the same session id, so every read path must
    honor the ``source`` parameter. (The export half is covered separately in
    test_export_session_scopes_by_source; this binds all three together.)
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)
        storage.upsert_session(Session(session_id="dup", summary="Claude one", source="claude"))
        storage.upsert_session(Session(session_id="dup", summary="Codex two", source="codex"))
        storage.insert_events(
            [
                _make_event(
                    event_id="c1", session_id="dup", text="CLAUDEMARKER alpha", source="claude"
                ),
                _make_event(
                    event_id="x1", session_id="dup", text="CODEXMARKER beta", source="codex"
                ),
            ]
        )
        storage.close()

        from fastapi.testclient import TestClient

        client = TestClient(create_app())

        # Detail: each source returns its own session row.
        claude_detail = client.get("/api/sessions/dup", params={"source": "claude"}).json()
        assert claude_detail["summary"] == "Claude one"
        codex_detail = client.get("/api/sessions/dup", params={"source": "codex"}).json()
        assert codex_detail["summary"] == "Codex two"

        # Export: source-scoped render contains only that tool's text.
        claude_export = client.get("/api/sessions/dup/export", params={"source": "claude"}).text
        assert "CLAUDEMARKER" in claude_export
        assert "CODEXMARKER" not in claude_export
        codex_export = client.get("/api/sessions/dup/export", params={"source": "codex"}).text
        assert "CODEXMARKER" in codex_export
        assert "CLAUDEMARKER" not in codex_export

        # Search: source filter bounds hits to that tool.
        claude_hits = client.get(
            "/api/search", params={"q": "CLAUDEMARKER", "source": "claude"}
        ).json()
        assert claude_hits["meta"]["total"] == 1
        assert "CLAUDEMARKER" in claude_hits["data"][0]["content_text"]
        codex_hits = client.get(
            "/api/search", params={"q": "CLAUDEMARKER", "source": "codex"}
        ).json()
        assert codex_hits["meta"]["total"] == 0
        # Un-scoped search still finds the unique claude term exactly once.
        unscoped = client.get("/api/search", params={"q": "CLAUDEMARKER"}).json()
        assert unscoped["meta"]["total"] == 1


# ── Concurrent scan re-trigger ────────────────────────────


def test_concurrent_scan_triggers_only_one(monkeypatch):
    """Burst-firing POST /api/scan from many threads must launch exactly one
    scan: the first wins, the rest get 409, and scan_all runs only once.

    The single-threaded tests (test_scan_lock_prevents_concurrent_scans,
    test_trigger_scan_409_when_already_running) prove the lock is atomic, but
    only a real concurrent burst exercises the race the lock exists to stop.
    """
    import threading
    import time

    from fastapi.testclient import TestClient

    import bagger.config as config
    from bagger.api import routes

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        config.settings = Settings(bagger_dir=Path(tmpdir))

        counter = {"n": 0}
        gate = threading.Lock()

        def slow_scan(*a, **k):
            with gate:
                counter["n"] += 1
            time.sleep(0.4)  # keep the lock held across the whole burst
            return {"sessions": 1, "events": 1, "skipped": 0, "errors": 0}

        monkeypatch.setattr(routes.sync, "scan_all", slow_scan)

        app = create_app()
        with TestClient(app) as client:
            statuses: list[int] = []
            barrier = threading.Barrier(8)

            def fire():
                barrier.wait()  # release all threads at the same instant
                statuses.append(client.post("/api/scan").status_code)

            threads = [threading.Thread(target=fire) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Wait out the single in-flight scan.
            for _ in range(100):
                if client.get("/api/scan/status").json()["running"] is False:
                    break
                time.sleep(0.05)

        # Exactly one scan ran; the other seven were refused.
        assert counter["n"] == 1, counter
        assert statuses.count(200) == 1, statuses
        assert statuses.count(409) == 7, statuses


def test_export_session_unsupported_format():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)
        storage.upsert_session(Session(session_id="sess-z", summary="Z"))
        storage.insert_events([_make_event(session_id="sess-z")])
        storage.close()

        from fastapi.testclient import TestClient

        client = TestClient(create_app())
        response = client.get("/api/sessions/sess-z/export?format=pdf")
        assert response.status_code == 400


def test_get_session_events_pagination():
    """/events supports page/per_page and caps per_page at 500 (P1)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)
        storage.upsert_session(Session(session_id="sess-p", summary="Paging"))
        storage.insert_events(
            [_make_event(event_id=f"p{i}", session_id="sess-p", text=f"msg {i}") for i in range(5)]
        )
        storage.close()

        from fastapi.testclient import TestClient

        client = TestClient(create_app())

        # Page 1, per_page=2 → 2 events, total 5.
        r1 = client.get("/api/sessions/sess-p/events?page=1&per_page=2")
        assert r1.status_code == 200
        j1 = r1.json()
        assert j1["meta"]["total"] == 5
        assert len(j1["data"]) == 2
        assert j1["meta"]["page"] == 1
        assert j1["meta"]["per_page"] == 2

        # Page 3 picks up the last item.
        r3 = client.get("/api/sessions/sess-p/events?page=3&per_page=2")
        assert len(r3.json()["data"]) == 1

        # per_page beyond the cap is rejected with 422 (not silently clamped).
        big = client.get("/api/sessions/sess-p/events?per_page=9999")
        assert big.status_code == 422


def test_get_session_events_not_found():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)
        storage.close()

        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)

        response = client.get("/api/sessions/nonexistent/events")
        assert response.status_code == 404


def test_search_english():
    """English query returns FTS5 results with snippets."""
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)

        e1 = _make_event(
            event_id="e-s1",
            session_id="s-s",
            role=Role.USER,
            text="Fix the authentication token expiration bug",
        )
        e2 = _make_event(
            event_id="e-s2",
            session_id="s-s",
            role=Role.ASSISTANT,
            text="The token refresh flow needs to handle edge cases",
        )
        storage.insert_events([e1, e2])
        storage.close()

        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)

        response = client.get("/api/search?q=token")
        assert response.status_code == 200
        data = response.json()
        assert data["meta"]["total"] >= 1
        # FTS5 should return snippets with <mark> tags
        assert "snippet" in data["data"][0]


def test_search_chinese():
    """CJK query uses FTS5 with jieba pre-tokenization (snippets present)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)

        e1 = _make_event(
            event_id="e-cn-s1",
            session_id="s-cn",
            role=Role.USER,
            text="实现用户登录功能和密码重置流程",
        )
        storage.insert_event(e1)
        storage.close()

        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)

        response = client.get("/api/search?q=登录")
        assert response.status_code == 200
        data = response.json()
        assert data["meta"]["total"] >= 1
        assert "登录" in data["data"][0]["content_text"]
        assert "snippet" in data["data"][0]  # FTS5 snippet for CJK


def test_search_pagination():
    """Search respects pagination parameters."""
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)

        for i in range(5):
            storage.insert_event(
                _make_event(
                    event_id=f"e-sp-{i}",
                    session_id="s-sp",
                    text=f"Pagination test event number {i}",
                )
            )
        storage.close()

        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)

        r1 = client.get("/api/search?q=Pagination&page=1&per_page=3")
        assert r1.status_code == 200
        d1 = r1.json()
        assert len(d1["data"]) == 3
        assert d1["meta"]["pages"] == 2

        r2 = client.get("/api/search?q=Pagination&page=2&per_page=3")
        assert r2.status_code == 200
        d2 = r2.json()
        assert len(d2["data"]) == 2


def test_search_results_carry_source():
    """Every search hit must expose its originating tool via `source` (§5.5/(c))."""
    # Manual temp-dir cleanup: the sandbox file-lock shim (and external AV/
    # indexers) occasionally hold bagger.db open at teardown, so ignore_errors
    # keeps the assertion above from being masked by an environmental teardown
    # error rather than a real failure.
    td = Path(tempfile.mkdtemp())
    try:
        storage = _override_db(td)

        e1 = _make_event(
            event_id="e-src-1",
            session_id="s-src",
            role=Role.USER,
            text="The codex rollout created a new session",
            source="codex",
        )
        storage.insert_events([e1])
        storage.close()

        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)

        response = client.get("/api/search?q=codex")
        assert response.status_code == 200
        data = response.json()
        assert data["meta"]["total"] >= 1
        assert data["data"][0]["source"] == "codex"
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_search_filters_by_source():
    """?source= scopes search hits (and meta.total) to one AI tool (§5.5/(b))."""
    td = Path(tempfile.mkdtemp())
    try:
        storage = _override_db(td)

        storage.insert_events(
            [
                _make_event(
                    event_id="e-cl-1",
                    session_id="s-cl",
                    text="shared token refresh helper",
                    source="claude",
                ),
                _make_event(
                    event_id="e-cx-1",
                    session_id="s-cx",
                    text="shared token refresh helper",
                    source="codex",
                ),
            ]
        )
        storage.close()

        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)

        # Unfiltered: both tools.
        all_resp = client.get("/api/search?q=token")
        all_data = all_resp.json()
        assert all_data["meta"]["total"] == 2

        # Scoped to codex: only the codex hit, and total reflects it.
        cx_resp = client.get("/api/search?q=token&source=codex")
        cx_data = cx_resp.json()
        assert cx_data["meta"]["total"] == 1
        assert cx_data["data"][0]["source"] == "codex"
        assert cx_data["data"][0]["source"] != "claude"
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_stats():
    """GET /api/stats returns aggregate counts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)

        storage.upsert_session(Session(session_id="s-st", summary="Stats test"))
        storage.insert_events(
            [
                _make_event(event_id="e-st-1", session_id="s-st", role=Role.USER),
                _make_event(event_id="e-st-2", session_id="s-st", role=Role.ASSISTANT),
                _make_event(event_id="e-st-3", session_id="s-st", role=Role.ASSISTANT),
            ]
        )
        storage.close()

        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)

        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_sessions"] == 1
        assert data["total_events"] == 3
        assert data["user_events"] == 1
        assert data["assistant_events"] == 2


def test_stats_daily():
    """GET /api/stats/daily returns time-series data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)

        storage.insert_event(
            _make_event(event_id="e-daily-1", session_id="s-d", text="Daily stats test message")
        )
        storage.close()

        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)

        response = client.get("/api/stats/daily?days=7")
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert "meta" in data
        assert data["meta"]["days"] == 7


def test_session_tree_endpoint_returns_forest():
    """GET /api/sessions/{id}/tree returns nested topology."""
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)

        root = _make_event(
            event_id="e-root", session_id="sess-1", role=Role.USER, parent_event_id=None
        )
        child = _make_event(
            event_id="e-child", session_id="sess-1", role=Role.ASSISTANT, parent_event_id="e-root"
        )
        storage.insert_event(root)
        storage.insert_event(child)
        storage.upsert_event_edges([root, child])
        storage.upsert_session(Session(session_id="sess-1", summary="demo", message_count=2))
        storage.close()

        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)

        resp = client.get("/api/sessions/sess-1/tree")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["event_id"] == "e-root"
        assert data[0]["depth"] == 0
        assert data[0]["children"][0]["event_id"] == "e-child"
        assert data[0]["children"][0]["depth"] == 1

        # Unknown session -> 404
        resp404 = client.get("/api/sessions/nope/tree")
        assert resp404.status_code == 404


def test_cors_is_locked_not_wildcard():
    """CORS must not use a wildcard: only configured origins are echoed back."""
    import bagger.config as config

    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        # Override allowed origins so we deterministically know the allow-list.
        config.settings = Settings(bagger_dir=td, cors_origins=["http://allowed.test"])

        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)

        # An allowed origin is reflected in the CORS response header.
        ok = client.get("/api/health", headers={"Origin": "http://allowed.test"})
        assert ok.status_code == 200
        assert ok.headers.get("access-control-allow-origin") == "http://allowed.test"

        # A disallowed origin must NOT be echoed (no "*", no leak to evil sites).
        bad = client.get("/api/health", headers={"Origin": "http://evil.test"})
        assert "access-control-allow-origin" not in bad.headers


def test_lifespan_per_request_storage_isolated():
    """Each request gets its own Storage connection (not a shared singleton).

    SQLite connections are not safe to share across threads, and FastAPI runs
    sync endpoints in a threadpool. We open a fresh connection per request so
    concurrent requests never touch the same connection object. Lock this in:
    two ``get_storage()`` calls yield DISTINCT, connected instances, and real
    requests still succeed.
    """
    from fastapi.testclient import TestClient

    import bagger.config as config
    from bagger.api.dependencies import get_storage

    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        config.settings = Settings(bagger_dir=td)

        app = create_app()
        with TestClient(app) as client:  # triggers lifespan
            with get_storage() as s1, get_storage() as s2:
                # Distinct instances — never the same connection object.
                assert s1 is not s2
                # Both are usable / connected.
                assert s1.get_stats()["total_events"] == 0
                assert s2.get_stats()["total_events"] == 0

            # A real request still works end-to-end.
            resp = client.get("/api/health")
            assert resp.status_code == 200


def test_scan_endpoint_runs_in_background(monkeypatch):
    """POST /api/scan returns immediately and the result is pollable via status.

    Locks in the A2 trigger-and-poll design: the endpoint must not block for the
    whole scan (the old behavior) and must expose the final stats through
    GET /api/scan/status so the UI can render sessions/events/skipped.
    """
    from fastapi.testclient import TestClient

    import bagger.config as config
    from bagger.api import routes

    with tempfile.TemporaryDirectory() as tmpdir:
        config.settings = Settings(bagger_dir=Path(tmpdir))

        # Stub the actual filesystem scan so the test is fast and deterministic.
        monkeypatch.setattr(
            routes.sync,
            "scan_all",
            lambda *a, **k: {"sessions": 3, "events": 12, "skipped": 1, "errors": 0},
        )

        app = create_app()
        with TestClient(app) as client:
            resp = client.post("/api/scan")
            assert resp.status_code == 200
            assert resp.json() == {"status": "started"}

            status = client.get("/api/scan/status").json()
            assert status["running"] is False
            assert status["done"] is True
            assert status["result"]["sessions"] == 3
            assert status["result"]["events"] == 12

            # Full rescan uses the same path.
            resp2 = client.post("/api/scan/full")
            assert resp2.json() == {"status": "started"}
            status2 = client.get("/api/scan/status").json()
            assert status2["done"] is True
            assert status2["result"]["skipped"] == 1


def test_scan_lock_prevents_concurrent_scans():
    """The in-process scan lock is atomic: only one scan may run at a time.

    A second trigger (incremental or full) while a scan is in flight must be
    rejected so overlapping scans can't race on the DB / watch state.
    """
    from bagger.api.scan_state import ScanStateStore

    store = ScanStateStore()
    # First trigger claims the single slot.
    assert store.try_acquire(full=False) is True
    assert store.is_running() is True
    # Concurrent triggers are rejected regardless of kind.
    assert store.try_acquire(full=False) is False
    assert store.try_acquire(full=True) is False
    # Once this scan finishes, a new one (even a full rescan) can start.
    store.mark_done({"sessions": 1, "events": 1, "skipped": 0, "errors": 0})
    assert store.is_running() is False
    assert store.try_acquire(full=True) is True


def test_trigger_scan_409_when_already_running():
    """POST /api/scan (and /api/scan/full) returns 409 while a scan runs."""
    from fastapi.testclient import TestClient

    from bagger.api.scan_state import scan_state

    # Pretend a scan is already in flight (no task will release it here).
    scan_state.try_acquire(False)
    try:
        client = TestClient(create_app())
        r1 = client.post("/api/scan")
        assert r1.status_code == 409
        # A full rescan must also be refused while the incremental is running.
        r2 = client.post("/api/scan/full")
        assert r2.status_code == 409
        # Status still reports the in-flight scan; nothing new was started.
        assert client.get("/api/scan/status").json()["running"] is True
    finally:
        scan_state.mark_done({"sessions": 0, "events": 0, "skipped": 0, "errors": 0})
