#!/usr/bin/env python3
"""Build the bagger backend as a standalone sidecar executable using PyInstaller.

Usage:
    python scripts/build-backend.py

This creates dist/bagger-server.exe and copies it to the Tauri sidecar directory
with the platform-specific naming convention required by Tauri's externalBin.

Prerequisites:
    pip install bagger[bundle]   (or: pip install pyinstaller>=6.0)
"""

import os
import platform
import shutil
import subprocess
import sys


def get_target_triple() -> str:
    """Return the Rust target triple for the current platform."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "windows" and machine == "amd64":
        return "x86_64-pc-windows-msvc"
    elif system == "darwin" and machine == "arm64":
        return "aarch64-apple-darwin"
    elif system == "darwin" and machine == "x86_64":
        return "x86_64-apple-darwin"
    elif system == "linux" and machine == "x86_64":
        return "x86_64-unknown-linux-gnu"
    else:
        raise RuntimeError(f"Unsupported platform: {system}-{machine}")


def main() -> None:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_tauri = os.path.join(project_root, "ui", "src-tauri")
    binaries_dir = os.path.join(src_tauri, "binaries")
    dist_dir = os.path.join(project_root, "dist")

    triple = get_target_triple()
    ext = ".exe" if platform.system() == "Windows" else ""
    sidecar_name = f"bagger-server-{triple}{ext}"

    print(f"Building sidecar for {triple}...")

    # Step 1: PyInstaller build
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--onefile",
            "--name",
            "bagger-server",
            "--hidden-import",
            "bagger.api.app",
            "--hidden-import",
            "bagger.cli.main",
            "--hidden-import",
            "uvicorn.logging",
            "--hidden-import",
            "uvicorn.lifespan.on",
            "--hidden-import",
            "uvicorn.lifespan.off",
            "--hidden-import",
            "uvicorn.protocols.http.auto",
            "--hidden-import",
            "uvicorn.protocols.websockets.auto",
            "--hidden-import",
            "uvicorn.protocols.websockets.wsproto_impl",
            "--hidden-import",
            "uvicorn.protocols.websockets.websockets_impl",
            "--hidden-import",
            "fastapi",
            "--hidden-import",
            "starlette",
            "--hidden-import",
            "starlette.routing",
            "--hidden-import",
            "click",
            "--hidden-import",
            "pydantic",
            "--distpath",
            dist_dir,
            "--workpath",
            os.path.join(project_root, "build", "sidecar"),
            "--specpath",
            os.path.join(project_root, "build"),
            "--noconfirm",
            os.path.join(project_root, "bagger", "cli", "main.py"),
        ],
        check=True,
    )

    # Step 2: Copy to Tauri sidecar directory with target-triple naming
    os.makedirs(binaries_dir, exist_ok=True)
    src = os.path.join(dist_dir, f"bagger-server{ext}")
    dst = os.path.join(binaries_dir, sidecar_name)
    shutil.copy2(src, dst)
    print(f"Sidecar copied: {dst}")

    # Step 3: Clean up PyInstaller artifacts (keep only dist/bagger-server)
    build_dir = os.path.join(project_root, "build")
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)
    print("Build artifacts cleaned up.")
    print(f"\nDone! Sidecar ready at: {dst}")
    print("Next step: npm run tauri build (from ui/ directory)")


if __name__ == "__main__":
    main()
