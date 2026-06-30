from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bagger.api.routes import health, search, sessions, stats


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Bagger API",
        description="REST API for browsing, searching, and replaying Claude Code conversation history.",
        version="0.2.0",
    )

    # Allow all local origins (dev server and Tauri webview)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routes
    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(sessions.router, prefix="/api", tags=["sessions"])
    app.include_router(search.router, prefix="/api", tags=["search"])
    app.include_router(stats.router, prefix="/api", tags=["stats"])

    return app
