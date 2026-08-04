"""GET /api/sessions/{id}/export — download a session as Markdown (or other formats)."""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from bagger.api.dependencies import get_storage
from bagger.exporters.markdown import SUPPORTED_FORMATS, render_session

router = APIRouter()


@router.get("/sessions/{session_id}/export")
def export_session(
    session_id: str,
    fmt: str = Query("markdown", alias="format", description="Export format (markdown)"),
) -> PlainTextResponse:
    """Render a session as a downloadable document (Markdown by default).

    Supports prefix matching for ``session_id`` like the other session routes.
    Returns ``text/markdown`` with a ``Content-Disposition`` filename hint.
    """
    if fmt not in SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format '{fmt}'. Supported: {', '.join(SUPPORTED_FORMATS)}",
        )

    with get_storage() as storage:
        session = storage.get_session(session_id)
        if session is None:
            session = storage.find_session_by_prefix(session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="Session not found")
            session_id = session["id"]

        events = storage.get_session_events(session_id)

        # Resolve a browser-friendly filename: source + short id, no path chars.
        safe_id = session_id.replace("/", "_")[:24]
        filename = f"bagger-{session.get('source', 'session')}-{safe_id}.md"

        body = render_session(session, events, fmt=fmt)

    return PlainTextResponse(
        body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
