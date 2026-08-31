"""Scan endpoints — trigger a background import and poll its status.

``POST /api/scan`` and ``POST /api/scan/full`` kick off ``scan_all`` as a
FastAPI ``BackgroundTask`` and return immediately with ``{"status": "started"}``.
The long-running scan writes progress to the shared ``scan_state`` store; the UI
polls ``GET /api/scan/status`` and renders the final stats (sessions / events /
skipped) when it completes.

This replaces the old synchronous behavior, which blocked the worker thread for
the whole scan and could stall other requests. See the code-review plan (item
A2): keeping the endpoint synchronous would have broken the frontend's
sessions/events/skipped display, so we move to a trigger-and-poll model instead.
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException

from bagger.api.scan_state import scan_state
from bagger.services.scanner import scan_all

router = APIRouter()


def _run_scan(full: bool) -> None:
    """Run ``scan_all`` off the request path and publish its result to scan_state.

    Runs in a FastAPI background task (a threadpool worker), so the triggering
    HTTP request returns before the scan finishes. The scan slot is claimed
    atomically by ``scan_state.try_acquire`` at trigger time (see the routes
    below), so this task just runs and publishes its outcome. Any failure is
    recorded via ``scan_state.mark_error`` and surfaced to the poller rather than
    crashing the worker or the request.
    """
    try:
        from bagger.storage import create_storage

        storage = create_storage()
        try:
            result = scan_all(storage, full=full)
        finally:
            storage.close()
    except Exception as exc:  # surface, don't crash the background worker
        scan_state.mark_error(str(exc))
        return
    scan_state.mark_done(result)


@router.post("/scan")
def trigger_scan(background_tasks: BackgroundTasks) -> dict:
    """Start an incremental scan in the background; returns immediately.

    If a scan (incremental or full) is already running, refuses with 409 so
    concurrent triggers can't launch overlapping scans that race on the
    database / watch state. The caller should poll ``GET /api/scan/status``.
    """
    if not scan_state.try_acquire(False):
        raise HTTPException(
            status_code=409,
            detail="A scan is already in progress. Poll GET /api/scan/status to follow it.",
        )
    background_tasks.add_task(_run_scan, False)
    return {"status": "started"}


@router.post("/scan/full")
def trigger_full_scan(background_tasks: BackgroundTasks) -> dict:
    """Start a full re-scan in the background; returns immediately.

    Same single-slot guard as ``/scan``: an in-flight scan (of either kind)
    makes this return 409.
    """
    if not scan_state.try_acquire(True):
        raise HTTPException(
            status_code=409,
            detail="A scan is already in progress. Poll GET /api/scan/status to follow it.",
        )
    background_tasks.add_task(_run_scan, True)
    return {"status": "started"}


@router.get("/scan/status")
def scan_status() -> dict:
    """Current background-scan status. Poll this after triggering a scan."""
    return scan_state.get()
