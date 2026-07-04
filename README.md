# bagger

> AI Coding Agent Data Collector — sync Claude Code transcripts into a searchable local database with a web UI.

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-261230.svg)](https://docs.astral.sh/ruff/)
[![Tests](https://img.shields.io/badge/tests-33%20passing-brightgreen.svg)](#development)

bagger reads the JSONL transcripts that Claude Code writes to `~/.claude/projects/` and turns them into a queryable SQLite database with FTS5 full-text search and session replay. Think of it as your AI coding memory layer — with a visual memory browser on top.

## Why

Claude Code already records everything you and the assistant say — every prompt, response, tool call, and thinking block. But those JSONL files sit in `~/.claude/projects/` as raw append-only logs. bagger makes them searchable and browsable.

```
~/.claude/projects/<hash>/<uuid>.jsonl    # raw transcript
          │
          ▼
       bagger
          │
          ▼
    ~/.bagger/bagger.db                    # searchable SQLite (FTS5)
```

## Quick start

```bash
# 1. Install (with web deps for the desktop app)
pip install -e ".[web]"

# 2. Initialize
bagger init

# 3. Import your existing sessions
bagger scan

# 4. Search (CLI)
bagger search "token expiration"
bagger search "登录" -s abc123     # filter by session prefix

# 5. Replay a session
bagger replay abc123               # supports prefix matching

# 6. Start the desktop app
cd ui && npm install && npm run tauri dev
```

## Desktop App (Tauri)

bagger ships as a native desktop app with tray support:

- **Window**: 1200×800, dev mode closes normally, release hides to tray
- **Tray**: Left-click to show, right-click menu (Show / Quit)
- **Backend**: Two modes — **dev** (host Python + hot reload) or **production** (bundled sidecar exe)
- **Single instance**: Named mutex prevents duplicate windows on restart
- **UI**: React + Tailwind dark theme, Fira Sans + Fira Code

### Dev setup

```bash
# Prerequisites: Rust, Node.js 22+, Python 3.12+
pip install -e ".[web,dev]"
cd ui && npm install
npm run tauri dev               # Auto-spawns backend with --reload (hot reload ON)
```

Or start backend manually if you want to see logs:

```bash
bagger serve --reload           # Terminal 1: API (hot reload ON)
npm run tauri dev               # Terminal 2: Desktop
```

### Production build

```bash
# 1. Bundle Python backend into standalone sidecar exe
pip install -e ".[web,bundle]"
python scripts/build-backend.py

# 2. Build the desktop app (sidecar is automatically included)
cd ui && npm run tauri build
```

The resulting `.msi` installer is fully self-contained — no Python installation required on the user's machine.

## Commands

| Command | Description |
|---------|-------------|
| `bagger init` | Create `~/.bagger/` and initialize the database |
| `bagger scan` | Import all Claude Code sessions (use `--full` to re-import) |
| `bagger watch` | Continuously sync new events as you chat with Claude Code |
| `bagger search <query>` | FTS5 full-text search with BM25 ranking and snippet highlighting |
| `bagger replay <session_id>` | Replay an entire conversation in the terminal |
| `bagger stats` | Show session and event counts |
| `bagger doctor` | Run diagnostics (DB integrity, FTS status, Claude config) |
| `bagger rebuild-index` | Rebuild the FTS5 search index from all events |
| `bagger serve` | Start the REST API server (requires `pip install -e ".[web]"`) |
| `bagger serve --reload` | Start with hot reload — code changes auto-restart (dev mode) |

## REST API

`bagger serve` starts a FastAPI server on `http://localhost:8723` with interactive Swagger docs.

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | Database status, event/session counts, FTS state |
| `GET /api/sessions?page=1&per_page=50` | Paginated session list |
| `GET /api/sessions/{id}` | Session metadata |
| `GET /api/sessions/{id}/events` | All events for a session (content_blocks parsed) |
| `GET /api/search?q=...&page=1` | FTS5 full-text search with snippet highlighting |
| `GET /api/stats` | Aggregate stats (events, roles, tokens) |
| `GET /api/stats/daily?days=30` | Daily event/token time series |
| `GET /api/stats/tools?limit=15` | Most frequently used tools |
| `POST /api/scan` | Trigger incremental scan of new sessions |
| `POST /api/scan/full` | Trigger full re-scan of all sessions |

## Architecture

```
~/.claude/projects/<path>/<uuid>.jsonl
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
      bagger scan         bagger watch
    (batch import)       (tail polling)
          │                   │
          └─────────┬─────────┘
                    ▼
            ClaudeCodeParser
                    │
              MemoryEvent
                    │
                    ▼
         ~/.bagger/bagger.db (SQLite + FTS5)
                    │
          ┌─────────┼──────────┐
          ▼         ▼          ▼
       CLI      REST API    Tauri Desktop
     (Click)   (FastAPI)  (React + Rust)
```

### Search: FTS5 + LIKE hybrid

- **English/ASCII queries** → SQLite FTS5 with BM25 ranking and `<mark>` snippet highlighting
- **Chinese/CJK queries** → LIKE fallback (FTS5 unicode61 can't segment CJK)
- English search is fast and ranked; Chinese search is exhaustive but guarantees no misses

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
├── tests/                 # pytest suite (33 tests)
├── scripts/               # Build helpers (PyInstaller sidecar bundling)
├── ui/                    # Tauri + React desktop frontend
└── design/                # Design specs and assets
```

Dependency flow is strictly downward: `cli`/`api` → `services` → `parser`/`storage` → `models`. See [CONTRIBUTING.md](CONTRIBUTING.md) for the full layering rules.

## Tech stack

| Layer        | Technology                                             |
|--------------|--------------------------------------------------------|
| CLI          | Click                                                  |
| Data models  | Pydantic v2                                            |
| Parser       | stdlib `json` (streaming JSONL)                        |
| Storage      | SQLite + FTS5 (stdlib `sqlite3`)                       |
| REST API     | FastAPI + Uvicorn                                      |
| Desktop      | Tauri (Rust) + React + Tailwind                        |
| Lint/format  | ruff (replaces flake8 + isort + black)                 |
| Tests        | pytest + httpx (FastAPI TestClient)                    |
| Bundling     | PyInstaller (backend sidecar) + Tauri (desktop .msi)   |

## Data captured

From each Claude Code transcript, bagger extracts:

- User prompts
- Assistant responses (text)
- Thinking blocks (Claude's internal reasoning)
- Tool calls (name, arguments) and tool results
- Token usage (input / output)
- Model version
- Session metadata (working directory, git branch)

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -q            # 33 tests
```

### Code quality

We use **ruff** for linting and formatting (configured in `pyproject.toml`).
Run these before every commit:

```bash
ruff check .               # lint
ruff check . --fix         # auto-fix safe issues
ruff format .              # format
ruff format --check .      # CI-style check (no writes)
```

The pre-commit gate is: `ruff check . && ruff format --check . && pytest tests/ -q`.
If any of these fail, the PR is not ready.

See [CONTRIBUTING.md](CONTRIBUTING.md) for branching strategy, commit
conventions, the code review checklist, and the project's module layering rules.

## Contributing

Contributions are welcome. Before opening a PR, please read
[CONTRIBUTING.md](CONTRIBUTING.md) — it covers:

- Development setup and the ruff gate
- Project structure and dependency layering
- Git workflow (branch naming, Conventional Commits, PR process)
- Code review checklist
- How to add a new CLI command or API endpoint

## Roadmap

- [ ] CI pipeline (GitHub Actions: ruff + pytest on every PR)
- [ ] Pre-commit hook for ruff
- [ ] More exporters (Zvec, Markdown)
- [ ] CJK-aware FTS tokenizer for ranked Chinese search
- [ ] Config file (`~/.bagger/config.toml`) for non-default paths

## License

MIT
