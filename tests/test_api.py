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


# ---- /api/memories/search (semantic / hybrid retrieval) ----


def _seed_memories(storage, rows):
    """Insert (type, content, topics, source) rows and reindex the FTS table.

    Mirrors what the consolidation pipeline writes, but without the LLM client —
    we only need rows + a populated ``memory_fts`` so the endpoint has something
    to retrieve. ``content_hash`` is given a distinct value per row to satisfy
    the UNIQUE(index) added by migration v6.

    ``memory_records`` has FK(source, session_id) → sessions, so a session must
    exist for every *distinct* source we seed; we create one per source using a
    deterministic session id (``mem-sess-<source>``). This lets a single seed
    carry mixed sources (e.g. claude + codex) for source-filter tests.
    """
    import hashlib

    from bagger.models.event import Session

    # Satisfy the FK: one session per distinct source.
    seen: list[str] = []
    for _typ, _content, _topics, source in rows:
        if source not in seen:
            seen.append(source)
            storage.upsert_session(
                Session(session_id=f"mem-sess-{source}", summary="mem-seed", source=source)
            )

    for typ, content, topics, source in rows:
        digest = hashlib.sha1(content.encode("utf-8")).hexdigest()[:16]
        storage._conn.execute(
            "INSERT INTO memory_records(type, content, topics, confidence, "
            "source, session_id, created_at, content_hash) VALUES (?,?,?,?,?,?,?,?)",
            (
                typ,
                content,
                topics,
                0.9,
                source,
                f"mem-sess-{source}",
                "2026-06-30T12:00:00",
                digest,
            ),
        )
    storage.reindex_memory_fts()


def _seed_vectors(storage, embedder):
    """Embed every seeded memory record and persist it as a "memory" vector."""
    from bagger.storage.base import VectorItem

    rows = storage._conn.execute("SELECT id, content FROM memory_records ORDER BY id").fetchall()
    items = []
    for rid, content in rows:
        vec = embedder.embed_query(content)
        items.append(
            VectorItem(
                owner_type="memory",
                owner_id=str(rid),
                model=embedder.model_name,
                dim=len(vec),
                vector=vec,
                content_hash=f"v{rid}",
            )
        )
    storage.upsert_vectors(items)


def test_memories_search_fts_offline():
    """``mode=fts`` works with zero embedding config (BM25 only)."""
    import bagger.config as config

    td = Path(tempfile.mkdtemp())
    try:
        storage = _override_db(td)
        _seed_memories(
            storage,
            [
                (
                    "fact",
                    "Choose Zvec as the local vector storage backend",
                    "vector-db,selection",
                    "claude",
                ),
                (
                    "preference",
                    "The scrollbar uses a thin floating style",
                    "ui,scrollbar",
                    "claude",
                ),
            ],
        )
        storage.close()

        from fastapi.testclient import TestClient

        config.settings = Settings(bagger_dir=td)
        client = TestClient(create_app())

        resp = client.get("/api/memories/search?q=vector&mode=fts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "fts"
        assert data["query"] == "vector"
        assert data["count"] >= 1
        contents = [r["content"] for r in data["results"]]
        assert any("Zvec" in c for c in contents)
        # FTS result shape carries the storage fields the UI renders.
        first = data["results"][0]
        assert "id" in first and "type" in first and "content" in first
        assert "fused_score" in first
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_memories_search_invalid_mode_rejected():
    """An unknown mode must be rejected with 422, not silently coerced."""
    import bagger.config as config

    td = Path(tempfile.mkdtemp())
    try:
        _override_db(td).close()

        from fastapi.testclient import TestClient

        config.settings = Settings(bagger_dir=td)
        client = TestClient(create_app())

        resp = client.get("/api/memories/search?q=anything&mode=bogus")
        assert resp.status_code == 422
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_memories_search_vector_needs_embedder_returns_503(monkeypatch):
    """``mode=hybrid|vector`` without a reachable embedder surfaces 503 (no 500)."""
    import bagger.config as config

    td = Path(tempfile.mkdtemp())
    try:
        storage = _override_db(td)
        _seed_memories(
            storage,
            [
                (
                    "fact",
                    "Choose Zvec as the local vector storage backend",
                    "vector-db,selection",
                    "claude",
                )
            ],
        )
        storage.close()

        from fastapi.testclient import TestClient

        config.settings = Settings(bagger_dir=td)
        monkeypatch.setattr(
            "bagger.embedding.create_embedder",
            lambda *a, **k: (_ for _ in ()).throw(
                RuntimeError("embedding unavailable: no API key")
            ),
        )
        client = TestClient(create_app())

        resp = client.get("/api/memories/search?q=vector+database&mode=hybrid")
        assert resp.status_code == 503
        assert "embedding unavailable" in resp.json()["detail"]
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_memories_search_hybrid_with_fake_embedder(monkeypatch):
    """``mode=hybrid`` fuses vector + FTS when an embedder is configured.

    Uses the offline FakeEmbedder so the test is deterministic and network-free;
    it still exercises the full HybridSearch → storage → RRF path the real remote
    embedder uses.
    """
    import bagger.config as config
    from bagger.embedding.fake import FakeEmbedder

    td = Path(tempfile.mkdtemp())
    try:
        storage = _override_db(td)
        _seed_memories(
            storage,
            [
                (
                    "fact",
                    "Choose Zvec as the local vector storage backend",
                    "vector-db,selection",
                    "claude",
                ),
                (
                    "preference",
                    "The scrollbar uses a thin floating style",
                    "ui,scrollbar",
                    "claude",
                ),
            ],
        )
        embedder = FakeEmbedder(model="fake")
        _seed_vectors(storage, embedder)
        storage.close()

        from fastapi.testclient import TestClient

        # Point the API at the temp DB (the embedder is forced below).
        config.settings = Settings(bagger_dir=td)
        # Force the offline embedder regardless of configured provider, so the
        # test exercises the real HybridSearch → storage → RRF path with no key.
        monkeypatch.setattr(
            "bagger.embedding.create_embedder",
            lambda *a, **k: FakeEmbedder(model="fake"),
        )
        client = TestClient(create_app())

        resp = client.get("/api/memories/search?q=vector+database&mode=hybrid")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "hybrid"
        assert data["count"] >= 1
        # The vector-db record must outrank the unrelated scrollbar record.
        assert "Zvec" in data["results"][0]["content"]
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_memories_search_filters_by_source():
    """?source= scopes semantic recall to one AI tool (§5.5/(b)).

    Two memories from *different* tools both contain the query term ``vector``;
    without a filter both come back, but ``source=claude`` / ``source=codex``
    must narrow the result set to exactly that tool — mirroring ``/api/search``.
    Uses ``mode=fts`` so the test needs no embedder (offline, deterministic).
    """
    import bagger.config as config

    td = Path(tempfile.mkdtemp())
    try:
        storage = _override_db(td)
        _seed_memories(
            storage,
            [
                (
                    "fact",
                    "Choose Zvec as the local vector storage backend",
                    "vector-db,selection",
                    "claude",
                ),
                (
                    "fact",
                    "Chroma is another vector storage backend option",
                    "vector-db,selection",
                    "codex",
                ),
            ],
        )
        storage.close()

        from fastapi.testclient import TestClient

        config.settings = Settings(bagger_dir=td)
        client = TestClient(create_app())

        # No filter: both tools contribute a "vector" hit.
        all_resp = client.get("/api/memories/search?q=vector&mode=fts")
        assert all_resp.status_code == 200
        all_data = all_resp.json()
        assert all_data["mode"] == "fts"
        assert all_data["count"] == 2

        # source=claude → only the claude memory, and it carries source=claude.
        cl_resp = client.get("/api/memories/search?q=vector&mode=fts&source=claude")
        cl_json = cl_resp.json()
        assert cl_resp.status_code == 200
        assert cl_json["count"] == 1
        assert cl_json["results"][0]["source"] == "claude"

        # source=codex → only the codex memory.
        cx_resp = client.get("/api/memories/search?q=vector&mode=fts&source=codex")
        cx_json = cx_resp.json()
        assert cx_resp.status_code == 200
        assert cx_json["count"] == 1
        assert cx_json["results"][0]["source"] == "codex"
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_memories_list_filters_and_paginates():
    """GET /api/memories browses records with source/type filters + pagination.

    Unlike /memories/search this needs no embedder — pure SQL over memory_records.
    Seeds 4 records across 2 sources and 4 types, then checks: total count, a
    source filter, a type filter, combined source+type, pagination (offset +
    limit), and that ``topics`` comes back as a list (not the comma-joined DB
    string).
    """
    import bagger.config as config

    td = Path(tempfile.mkdtemp())
    try:
        storage = _override_db(td)
        _seed_memories(
            storage,
            [
                ("fact", "Zvec is the local vector storage backend", "vector-db,storage", "claude"),
                ("preference", "gc dislikes auto-starting the dev server", "habits,ux", "claude"),
                ("decision", "Chose Zvec over Chroma for vectors", "vector-db,selection", "codex"),
                ("lesson", "managed venv pip breaks; rebuild it", "python,tooling", "codex"),
            ],
        )
        storage.close()

        from fastapi.testclient import TestClient

        config.settings = Settings(bagger_dir=td)
        client = TestClient(create_app())

        # All four records; count + pagination meta are what we assert.
        all_resp = client.get("/api/memories")
        assert all_resp.status_code == 200
        all_json = all_resp.json()
        assert all_json["meta"]["total"] == 4
        assert len(all_json["data"]) == 4
        assert all_json["meta"]["pages"] == 1
        # topics normalized from the comma-joined DB string to a list.
        assert isinstance(all_json["data"][0]["topics"], list)

        # source filter narrows to one tool.
        cl_resp = client.get("/api/memories?source=claude")
        assert cl_resp.status_code == 200
        assert cl_resp.json()["meta"]["total"] == 2

        # type filter narrows to one kind.
        fact_resp = client.get("/api/memories?type=fact")
        assert fact_resp.status_code == 200
        fact_json = fact_resp.json()
        assert fact_json["meta"]["total"] == 1
        assert fact_json["data"][0]["type"] == "fact"

        # source + type combine (AND).
        combo = client.get("/api/memories?source=codex&type=lesson")
        assert combo.json()["meta"]["total"] == 1

        # Pagination: 2 per page → 2 pages; page 2 holds the remaining 2.
        p1 = client.get("/api/memories?per_page=2&page=1")
        assert p1.status_code == 200
        p1_json = p1.json()
        assert len(p1_json["data"]) == 2
        assert p1_json["meta"]["pages"] == 2
        assert p1_json["meta"]["page"] == 1

        p2 = client.get("/api/memories?per_page=2&page=2")
        assert len(p2.json()["data"]) == 2
        assert p2.json()["meta"]["page"] == 2
    finally:
        shutil.rmtree(td, ignore_errors=True)
