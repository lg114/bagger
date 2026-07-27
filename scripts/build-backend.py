#!/usr/bin/env python3
"""Build the bagger backend as a standalone Tauri sidecar executable.

Usage:
    python scripts/build-backend.py

This runs PyInstaller against ``scripts/bagger-server.spec`` (which freezes
``bagger/sidecar_main.py`` — the serve-only entry) and copies the resulting
binary into the Tauri sidecar directory with the platform-specific naming
Tauri expects.

Prerequisites — build from a CLEAN virtual environment, NOT your dev env:
    python -m venv .venv-bundle
    source .venv-bundle/bin/activate        # Windows: .venv-bundle\\Scripts\\activate
    pip install -e ".[web,bundle]"          # NOTE: no [dev] -> keeps pytest/ruff/httpx out
    python scripts/build-backend.py
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

    mapping = {
        ("windows", "amd64"): "x86_64-pc-windows-msvc",
        ("windows", "x86_64"): "x86_64-pc-windows-msvc",
        ("darwin", "arm64"): "aarch64-apple-darwin",
        ("darwin", "x86_64"): "x86_64-apple-darwin",
        ("linux", "x86_64"): "x86_64-unknown-linux-gnu",
        ("linux", "amd64"): "x86_64-unknown-linux-gnu",
    }
    key = (system, machine)
    if key not in mapping:
        raise RuntimeError(f"Unsupported platform: {system}-{machine}")
    return mapping[key]


def main() -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = os.path.join(root, "scripts", "bagger-server.spec")
    dist_dir = os.path.join(root, "dist")
    binaries_dir = os.path.join(root, "ui", "src-tauri", "binaries")

    triple = get_target_triple()
    ext = ".exe" if platform.system() == "Windows" else ""
    sidecar_name = f"bagger-server-{triple}{ext}"

    print(f"Building sidecar for {triple}...")

    # Step 1: PyInstaller build from the spec (--clean avoids stale cache).
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            dist_dir,
            "--workpath",
            os.path.join(root, "build", "sidecar"),
            spec,
        ],
        check=True,
        cwd=root,
    )

    # Step 2: Copy to Tauri sidecar directory with target-triple naming.
    os.makedirs(binaries_dir, exist_ok=True)
    src = os.path.join(dist_dir, f"bagger-server{ext}")
    dst = os.path.join(binaries_dir, sidecar_name)
    shutil.copy2(src, dst)
    print(f"Sidecar copied: {dst}")

    # Step 3: Clean up PyInstaller intermediate artifacts (keep dist/).
    build_dir = os.path.join(root, "build")
    if os.path.isdir(build_dir):
        shutil.rmtree(build_dir)
    print("Build artifacts cleaned up.")
    print(f"\nDone! Sidecar ready at: {dst}")
    print("Next step: npm run tauri build (from ui/ directory)")


if __name__ == "__main__":
    main()
