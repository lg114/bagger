# Contributing to bagger

Thanks for working on bagger. This document is the single source of truth for
how we write, review, and ship code. Read it once; follow it always.

## Quick start

```bash
# Prerequisites: Python 3.12+, Node.js 22+, Rust (for Tauri builds)
pip install -e ".[dev,web]"
cd ui && npm install      # only if you touch the desktop app
pytest tests/ -q          # 33 tests, should be green
```

## Code style

We use **ruff** for both linting and formatting. The config lives in
`pyproject.toml` under `[tool.ruff]`. There is no separate black/flake8/isort
setup — ruff replaces all of them.

```bash
ruff check .              # lint
ruff check . --fix        # auto-fix safe issues
ruff format .             # format
```

**Before every commit**, run:

```bash
ruff check . && ruff format --check . && pytest tests/ -q
```

If any of these fail, the PR is not ready. No exceptions.

### CI — this runs on every push and PR

GitHub Actions (`.github/workflows/ci.yml`) runs the same three gates on
**Python 3.12 and 3.13** every time you push to `main` or open a PR:

1. `ruff check .` — lint must pass
2. `ruff format --check .` — formatting must be clean
3. `pytest tests/ -q` — all tests must pass

If any step fails, the PR shows a red ✗ and **cannot be merged** (once branch
protection is enabled). The CI gates are identical to the local pre-commit
gate — if it passes locally, it passes in CI.

### What the rules enforce

- `E` / `F` — basic style and undefined-name / unused-import checks
- `I` — import ordering (isort-compatible)
- `UP` — modern syntax (`Optional[X]` → `X | None`, `datetime.UTC`, etc.)
- `B` — common bug-bear pitfalls
- `SIM` — simpler idioms

If you genuinely need to silence a rule, use `# noqa: <code>` with a
short justification on the same line. Blind `# noqa` without a reason will
be rejected in review.

## Project structure

```
bagger/
├── bagger/                # Python package
│   ├── cli/               # Click commands (init, scan, watch, search, ...)
│   ├── api/               # FastAPI app + routes (health, sessions, search, stats, sync)
│   ├── models/            # Pydantic data models (MemoryEvent, Session, WatchState)
│   ├── parser/            # Claude Code JSONL → MemoryEvent
│   ├── storage/           # SQLite + FTS5 storage layer
│   ├── services/          # Business logic (scanner, watcher, search, replay)
│   └── exporters/         # Export abstractions (base, jsonl)
├── tests/                 # pytest suite
├── scripts/               # Build helpers (PyInstaller sidecar bundling)
├── ui/                    # Tauri + React desktop frontend
└── design/                # Design specs and assets
```

### Layering rules

Dependencies flow **downward only**. Do not introduce upward imports:

```
cli / api  →  services  →  parser / storage  →  models
```

- `models/` depends on nothing but pydantic.
- `parser/` and `storage/` depend on `models/`.
- `services/` depends on `parser/`, `storage/`, `models/`.
- `cli/` and `api/` depend on `services/` and below.

If you find yourself importing `storage` from `models`, or `services` from
`parser`, stop — the layering is wrong.

## Testing

- Every new feature or bug fix comes with a test.
- Tests live in `tests/` and mirror the package layout (`test_storage.py`,
  `test_parser.py`, `test_api.py`, ...).
- Use the existing fixtures in `tests/conftest.py` for temp DBs and sample
  transcripts — don't roll your own.
- API tests use FastAPI's `TestClient` (httpx-backed). No live server needed.
- Run `pytest tests/ -q` before pushing. If you break a test, fix it; do not
  skip it without a written reason in the PR description.

## Git workflow

### Branching

- `main` is always shippable. Never commit directly to `main`.
- Branch from `main` with a descriptive name:
  - `feat/<short-description>` — new capability
  - `fix/<short-description>` — bug fix
  - `refactor/<short-description>` — internal cleanup, no behavior change
  - `docs/<short-description>` — documentation only
  - `chore/<short-description>` — deps, tooling, CI

### Commit messages

We follow **Conventional Commits**. One change per commit when possible.

```
feat(api): add daily token time-series endpoint
fix(storage): handle empty transcript lines without crashing
refactor(parser): split entry parsing into smaller functions
docs(readme): document project structure and dev workflow
chore(deps): pin ruff and add httpx to dev extras
```

- Subject line ≤ 72 chars, imperative mood (`add`, not `added`).
- Body explains *why*, not *what* — the diff already shows what.
- Reference issues in the footer: `Closes #42`.

### Pull requests

- Keep PRs small and focused. If it needs more than ~400 lines of diff to
  explain, it should probably be multiple PRs.
- Fill in the PR template (scope, what changed, how to test, risks).
- Request at least one reviewer. Don't self-merge.
- If a review requests changes, address them or push back with reasoning —
  silent re-push without replying will be reverted.

## Code review checklist

Reviewers, look for these in order. Authors, self-review against the same
list before requesting review.

1. **Correctness** — Does it do what the PR says? Edge cases handled?
2. **Tests** — Are new behaviors covered? Did any existing test get weaker?
3. **Layering** — Does it respect the dependency flow above?
4. **Types** — Public functions have type annotations? No `Any` without reason?
5. **Errors** — Failures are handled, not swallowed. No bare `except: pass`.
6. **Naming** — Names say what, not how. No `data2`, `tmp`, `do_thing`.
7. **Style** — Passes `ruff check` and `ruff format --check`.
8. **Docs** — Public API has docstrings. Non-obvious decisions have comments.

Style nits (import order, line length) are ruff's job — do not hand-review
what the linter already enforces. Spend review time on logic and design.

## Adding a new CLI command

1. Add the command function in `bagger/cli/main.py` under a `# ── <name> ──`
   section, decorated with `@cli.command()` and (if it needs the DB)
   `@require_db()` + `@with_storage`.
2. Add it to the Commands table in `README.md`.
3. Add a test in `tests/` that exercises the happy path.
4. Run `ruff check . && pytest tests/ -q`.

## Adding a new API endpoint

1. Create or extend a router in `bagger/api/routes/`.
2. Register it in `bagger/api/app.py` under the right `prefix` and `tags`.
3. Document it in the REST API table in `README.md`.
4. Add a test in `tests/test_api.py` using `TestClient`.

## Reporting issues

- Bugs: include the command you ran, expected vs actual output, and your OS.
- Feature requests: describe the use case first, the solution second.

## License

By contributing, you agree your contributions are licensed under the project's
MIT license.
