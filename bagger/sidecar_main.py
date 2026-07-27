"""Production sidecar entry point — API server only.

This is the module PyInstaller freezes into the Tauri sidecar. Unlike the full
CLI (``bagger/cli/main.py``) it exposes ONLY the serve surface: no Click command
group, no ``webbrowser.open``, no scan/watch/replay/doctor logic. That keeps the
frozen binary small and avoids pulling dev-only code paths into the bundle.

The frontend (Tauri) launches this binary; it listens on 127.0.0.1:8723 by
default. ``--host`` / ``--port`` are parsed minimally in case Tauri passes them.
"""

from __future__ import annotations

import multiprocessing
import sys
from contextlib import suppress


def main() -> None:
    # Required on Windows + PyInstaller for correct subprocess/lifecycle behavior.
    multiprocessing.freeze_support()

    host = "127.0.0.1"
    port = 8723

    # Minimal argv parsing — Tauri may pass --host/--port to the sidecar.
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--host" and i + 1 < len(args):
            host = args[i + 1]
            i += 2
        elif args[i] == "--port" and i + 1 < len(args):
            with suppress(ValueError):
                port = int(args[i + 1])
            i += 2
        else:
            i += 1

    import uvicorn

    uvicorn.run(
        "bagger.api.app:create_app",
        host=host,
        port=port,
        factory=True,
        log_level="info",
        reload=False,  # never reload in production
        workers=1,     # single-process sidecar is enough
    )


if __name__ == "__main__":
    main()
