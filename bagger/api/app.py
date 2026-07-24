from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bagger import __version__
from bagger.api.dependencies import set_shared_storage
from bagger.api.routes import health, search, sessions, stats, sync
from bagger.storage import create_storage


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open a single shared DB connection for the app's lifetime.

    One connection is created at startup and reused by every request handler
    (see :func:`bagger.api.dependencies.get_storage`), removing the
    per-request connect/close overhead. It is closed on shutdown.
    """
    storage = create_storage()
    set_shared_storage(storage)
    try:
        yield
    finally:
        set_shared_storage(None)
        storage.close()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    from bagger.config import settings

    app = FastAPI(
        title="Bagger API",
        description=(
            "REST API for browsing, searching, and replaying Claude Code conversation history."
        ),
        version=__version__,
        lifespan=lifespan,
    )

    # Lock CORS to configured (loopback) origins — never a wildcard.
    # The API can trigger real file scans (POST /api/scan), so an open policy
    # would let any website drive the user's local agent. allow_origins comes
    # from settings.cors_origins; override it in ~/.bagger/config.toml only
    # for origins you trust.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
        allow_credentials=False,
    )

    # Register routes
    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(sessions.router, prefix="/api", tags=["sessions"])
    app.include_router(search.router, prefix="/api", tags=["search"])
    app.include_router(stats.router, prefix="/api", tags=["stats"])
    app.include_router(sync.router, prefix="/api", tags=["sync"])

    return app
