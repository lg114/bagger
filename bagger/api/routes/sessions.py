"""Session API routes — list, detail, events (for conversation replay)."""

import json

from fastapi import APIRouter, HTTPException, Query, Response

from bagger.api.dependencies import get_storage

router = APIRouter()


def _dumps_tree(roots: list[dict]) -> str:
    """Iteratively serialize the session tree forest as a JSON array.

    The stdlib json encoder recurses once per nesting level and is bounded by
    the interpreter's *C* recursion limit, which ``sys.setrecursionlimit``
    cannot raise — a long linear session (>~1000 events in one parent chain)
    would raise RecursionError. This explicit-stack walk emits equivalent JSON
    (same separators as Starlette's JSONResponse) with no recursion at all:
    scalar fields are encoded with flat ``json.dumps`` calls and the
    ``children`` nesting is assembled from stack-driven fragments.
    """
    parts: list[str] = []
    # Stack entries: ("nodes", list) → children array; ("node", dict) → one
    # tree node; ("raw", str) → pre-encoded fragment or punctuation.
    stack: list = [("nodes", roots)]
    while stack:
        kind, val = stack.pop()
        if kind == "raw":
            parts.append(val)
        elif kind == "nodes":
            parts.append("[")
            stack.append(("raw", "]"))
            for i in range(len(val) - 1, -1, -1):
                stack.append(("node", val[i]))
                if i > 0:
                    stack.append(("raw", ","))
        else:  # ("node", dict)
            children = val.get("children") or []
            if children:
                # Open this node's object without its closing brace, then
                # splice in "children": [...] — the stack unwinds in order.
                flat = {k: v for k, v in val.items() if k != "children"}
                inner = ",".join(
                    f"{json.dumps(k, ensure_ascii=False, separators=(',', ':'))}:"
                    f"{json.dumps(v, ensure_ascii=False, separators=(',', ':'))}"
                    for k, v in flat.items()
                )
                stack.append(("raw", "}"))
                stack.append(("nodes", children))
                # Comma only when scalar fields precede "children" (never empty
                # here in practice, but a children-only node must not emit
                # a leading comma).
                stack.append(("raw", "{" + inner + ("," if inner else "") + '"children":'))
            else:
                flat = dict(val)
                flat["children"] = []
                stack.append(("raw", json.dumps(flat, ensure_ascii=False, separators=(",", ":"))))
    return "".join(parts)


@router.get("/sessions")
def list_sessions(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=200, description="Items per page"),
    sort: str = Query("last_message_at", description="Sort field"),
    order: str = Query("desc", description="Sort order (asc/desc)"),
    project: str | None = Query(None, description="Filter by exact project_path"),
    source: str | None = Query(None, description="Filter by source (e.g. claude, chatgpt)"),
) -> dict:
    """Paginated list of all sessions with configurable sorting.

    When ``project`` is provided (e.g. from the Projects page "View all"
    link), the result and its total count are scoped to that project so the
    Conversations page header matches the project's session count. When
    ``source`` is provided, only sessions from that AI tool are returned
    (multi-tool support, §5.5) — letting the frontend facet by source.
    """
    with get_storage() as storage:
        result = storage.list_sessions_paginated(
            page=page, per_page=per_page, sort=sort, order=order, project=project, source=source
        )
    return result


@router.get("/sources")
def list_sources(project: str | None = Query(None, description="Optional project scope")) -> dict:
    """Canonical list of every distinct source present in the store.

    Drives the source facet in the UI so users can filter by AI tool (claude,
    codex, …) even when that source's sessions don't appear on the first page
    of results.     An optional ``project`` scope narrows the facet to that project's
    sessions, keeping it consistent with the filtered Conversations list.
    """
    with get_storage() as storage:
        sources = storage.distinct_sources(project=project)
    return {"sources": sources}


@router.get("/sessions/{session_id}")
def get_session(
    session_id: str,
    source: str | None = Query(
        None, description="Originating tool (claude, codex, …). Disambiguates shared ids."
    ),
) -> dict:
    """Get metadata for a single session."""
    with get_storage() as storage:
        session = storage.get_session(session_id, source=source)
        if session is None:
            # Try prefix match via SQL LIKE (scoped to source when given)
            session = storage.find_session_by_prefix(session_id, source=source)
            if session is None:
                raise HTTPException(status_code=404, detail="Session not found")
        return session


@router.get("/sessions/{session_id}/events")
def get_session_events(
    session_id: str,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=500, description="Events per page"),
    source: str | None = Query(
        None, description="Originating tool (claude, codex, …). Scopes events to that tool."
    ),
) -> dict:
    """Get events for a session, ordered by timestamp ascending, paginated.

    Returns content_blocks parsed from JSON for direct rendering. Use ``page``
    / ``per_page`` to stream long sessions instead of loading everything at once.
    """
    with get_storage() as storage:
        # Resolve session ID (support prefix matching via SQL LIKE)
        session = storage.get_session(session_id, source=source)
        if session is None:
            session = storage.find_session_by_prefix(session_id, source=source)
            if session is None:
                raise HTTPException(status_code=404, detail="Session not found")
            session_id = session["id"]

        result = storage.get_session_events_paginated(
            session_id, page=page, per_page=per_page, source=source
        )

    # Parse content_json into content_blocks for the frontend
    parsed_events = []
    for evt in result["data"]:
        evt = dict(evt)
        try:
            evt["content_blocks"] = json.loads(evt.pop("content_json", "[]"))
        except (json.JSONDecodeError, TypeError):
            evt["content_blocks"] = []
        parsed_events.append(evt)

    return {"data": parsed_events, "meta": result["meta"]}


@router.get("/sessions/{session_id}/tree")
def get_session_tree(
    session_id: str,
    source: str | None = Query(
        None, description="Originating tool (claude, codex, …). Scopes the topology to that tool."
    ),
) -> Response:
    """Get the session topology as a nested forest.

    Returns the event tree (branches, compactions, resumptions) derived from
    ``event_edges``. Supports prefix matching like the events endpoint.
    """
    with get_storage() as storage:
        session = storage.get_session(session_id, source=source)
        if session is None:
            session = storage.find_session_by_prefix(session_id, source=source)
            if session is None:
                raise HTTPException(status_code=404, detail="Session not found")
            session_id = session["id"]
        tree = storage.get_session_tree(session_id, source=source)

    # A long linear session nests 1000+ levels deep; serialize here with the
    # iterative encoder (see _dumps_tree) instead of letting FastAPI's
    # recursive json.dumps blow the C recursion limit.
    payload = '{"data":' + _dumps_tree(tree) + "}"
    return Response(content=payload, media_type="application/json")
