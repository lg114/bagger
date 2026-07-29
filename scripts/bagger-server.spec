# scripts/bagger-server.spec
# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the bagger Tauri sidecar.

Run via ``python scripts/build-backend.py`` (which calls
``pyinstaller scripts/bagger-server.spec``). Paths are resolved relative to this
file so the build works regardless of the current working directory.
"""

import os
import glob
import sys

# SPECPATH is provided by PyInstaller and points at this .spec's directory.
SPEC_DIR = SPECPATH
ROOT = os.path.dirname(SPEC_DIR)
ENTRY = os.path.join(ROOT, "bagger", "sidecar_main.py")

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

hiddenimports = [
    # ── API surface + routes ──
    "bagger.api.app",
    "bagger.api.dependencies",
    "bagger.api.routes.health",
    "bagger.api.routes.sessions",
    "bagger.api.routes.search",
    "bagger.api.routes.stats",
    "bagger.api.routes.sync",
    # ── storage / services / parser / models (pulled in at request time) ──
    "bagger.storage",
    "bagger.storage.base",
    "bagger.storage.sqlite",
    "bagger.services.sync",
    "bagger.services.scanner",
    "bagger.services.watcher",
    "bagger.services.search",
    "bagger.services.replay",
    "bagger.parsers",
    "bagger.parsers.base",
    "bagger.parsers.claude",
    "bagger.models.event",
    "bagger.exporters.jsonl",
    "bagger.config",
    # ── uvicorn dynamic imports (runtime-dispatched, must be explicit) ──
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    # ── runtime libs ──
    "fastapi",
    "starlette",
    "pydantic",
    "click",   # harmless to keep; not on the serve path but tiny
    "jieba",   # lazy-imported inside bagger.storage.sqlite — must be explicit
]

datas = []
# jieba lazy-loads its dictionary at runtime; bundle the data files or CJK
# search silently falls back to LIKE.
datas += collect_data_files("jieba")

# Package metadata so ``importlib.metadata.version("bagger")`` resolves inside
# the frozen binary (otherwise health/factory report "0.0.0"). Copies the
# ``.dist-info`` into _MEIPASS, which is on sys.path at runtime.
datas += copy_metadata("bagger")

# ── C-extension runtime DLLs ──
# On the managed-Python layout these live in <prefix>/DLLs/, and PyInstaller's
# built-in hooks (ssl/sqlite3/ctypes) miss them there, producing
# "ImportError: DLL load failed while importing _ssl" (or _sqlite3) at runtime.
# Collect them explicitly so the frozen binary can actually start.
binaries = []
_ssl_base = getattr(sys, "base_prefix", sys.prefix)  # real Python for venv builds
for _dll_dir in (os.path.join(_ssl_base, "DLLs"), _ssl_base):
    for _pat in ("libssl-*.dll", "libcrypto-*.dll", "sqlite3.dll", "libffi-*.dll"):
        for _d in glob.glob(os.path.join(_dll_dir, _pat)):
            binaries.append((_d, "."))

# Keep the bundle lean: drop test tooling and GUI/scientific libs that can be
# transitively pulled in from a dev venv. Build from a CLEAN venv with only
# ``pip install -e ".[web,bundle]"`` to avoid pytest/ruff/httpx leaking in.
excludes = [
    "tkinter",
    "matplotlib",
    "numpy",
    "pandas",
    "scipy",
    "PIL",
    "pytest",
    "unittest",
    "test",
    "tests",
    "httpx",
    "ruff",
    "pyinstaller",
    "IPython",
    "notebook",
]

a = Analysis(
    [ENTRY],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=1,  # strip asserts, keep docstrings (fastapi/pydantic rely on them)
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="bagger-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,           # leave off on Windows (needs toolchain, marginal gain)
    upx=False,             # reliability > a few MB (AV false-positives, slower start)
    console=True,          # sidecar logs to stdout; flip to windowed=True for silent UX
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
