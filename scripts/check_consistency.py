#!/usr/bin/env python3
"""Guard against docs and version drift.

Three checks, each comparing what the repo *says* against what the code *does*:

1. README CLI command table  vs the commands Click actually registered.
2. README API endpoint table vs the routes FastAPI actually registered.
3. pyproject.toml / ui/package.json / ui/src-tauri/tauri.conf.json /
   ui/src-tauri/Cargo.toml all report the same version.

Introspection (not static parsing) is deliberate: a guard that silently misses
a route is worse than no guard at all.

Exit code 0 = consistent, 1 = drift. Run from anywhere:

    python scripts/check_consistency.py
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

README = REPO_ROOT / "README.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"
PACKAGE_JSON = REPO_ROOT / "ui" / "package.json"
TAURI_CONF = REPO_ROOT / "ui" / "src-tauri" / "tauri.conf.json"
CARGO_TOML = REPO_ROOT / "ui" / "src-tauri" / "Cargo.toml"

HTTP_METHODS = frozenset({"GET", "POST", "PUT", "DELETE", "PATCH"})

# README writes `/api/sessions/{id}` while the route declares `{session_id}`.
# The parameter *name* is prose; only its presence matters here.
_PARAM = re.compile(r"\{[^}]*\}")

# Anchored to table rows only, so prose like "run `bagger init`" cannot sneak a
# phantom command into the documented set.
_CLI_ROW = re.compile(r"^\|\s*`bagger\s+([a-z][a-z0-9-]*)", re.MULTILINE)
_ENDPOINT_ROW = re.compile(r"^\|\s*`(GET|POST|PUT|DELETE|PATCH)\s+(/api/[^`\s]*)`", re.MULTILINE)


def _normalize(path: str) -> str:
    """Collapse path parameter names so `{id}` and `{session_id}` compare equal."""
    return _PARAM.sub("{}", path)


def readme_cli_commands() -> set[str]:
    return set(_CLI_ROW.findall(README.read_text(encoding="utf-8")))


def readme_endpoints() -> set[str]:
    matches = _ENDPOINT_ROW.findall(README.read_text(encoding="utf-8"))
    return {f"{method} {_normalize(path)}" for method, path in matches}


def actual_cli_commands() -> set[str]:
    from bagger.cli.main import cli

    return set(cli.commands)


def actual_endpoints() -> set[str]:
    # Read the OpenAPI schema rather than `app.routes`: FastAPI >= 0.116 keeps
    # `include_router` calls as `_IncludedRouter` wrappers (path=None) instead
    # of flattening them into `app.routes`, so walking that list finds nothing.
    # The schema is public, version-stable, and already has the /api prefix.
    from bagger.api.app import create_app

    paths = create_app().openapi().get("paths", {})
    return {
        f"{method.upper()} {_normalize(path)}"
        for path, operations in paths.items()
        for method in operations
        if method.upper() in HTTP_METHODS
    }


def _cargo_version() -> str | None:
    """Read `[package] version` — not one of the dependency versions below it."""
    section = ""
    for line in CARGO_TOML.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            section = stripped
            continue
        if section == "[package]" and re.match(r'^version\s*=\s*"', stripped):
            return stripped.split('"')[1]
    return None


def versions() -> dict[str, str | None]:
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return {
        "pyproject.toml": pyproject.get("project", {}).get("version"),
        "ui/package.json": json.loads(PACKAGE_JSON.read_text(encoding="utf-8")).get("version"),
        "ui/src-tauri/tauri.conf.json": json.loads(TAURI_CONF.read_text(encoding="utf-8")).get(
            "version"
        ),
        "ui/src-tauri/Cargo.toml": _cargo_version(),
    }


def _diff(label: str, documented: set[str], actual: set[str]) -> bool:
    stale = sorted(documented - actual)
    undocumented = sorted(actual - documented)
    if not stale and not undocumented:
        print(f"  ok    {label}: {len(actual)} checked")
        return True
    print(f"  FAIL  {label}:")
    for item in stale:
        print(f"          documented but not in code: {item}")
    for item in undocumented:
        print(f"          in code but not documented: {item}")
    return False


def _diff_versions(found: dict[str, str | None]) -> bool:
    distinct = set(found.values())
    if len(distinct) == 1 and None not in distinct:
        print(f"  ok    version: all {len(found)} files at {distinct.pop()}")
        return True
    print("  FAIL  version drift:")
    for name, value in found.items():
        print(f"          {name}: {value if value is not None else 'NOT FOUND'}")
    return False


def _failures(checks: Iterable[tuple[str, bool]]) -> int:
    return sum(1 for _, ok in checks if not ok)


def main() -> int:
    print("bagger consistency check")
    try:
        results = [
            ("CLI commands", _diff("CLI commands", readme_cli_commands(), actual_cli_commands())),
            ("API endpoints", _diff("API endpoints", readme_endpoints(), actual_endpoints())),
            ("version", _diff_versions(versions())),
        ]
    except ImportError as exc:
        print(f"  FAIL  cannot import the package: {exc}")
        print("        install it first: pip install -e '.[dev,web]'")
        return 1

    failed = _failures(results)
    print()
    if failed:
        print(f"FAIL: {failed} of {len(results)} checks drifted")
        return 1
    print(f"PASS: all {len(results)} checks consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
