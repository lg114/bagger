from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bagger.api.routes import health, search, sessions, stats, sync


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    from bagger.config import settings

    app = FastAPI(
        title="Bagger API",
        description=(
            "REST API for browsing, searching, and replaying Claude Code conversation history."
        ),
        version="0.2.0",
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
