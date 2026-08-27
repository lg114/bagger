<div align="center">

# bagger

**Scan local AI coding conversations. Search them. Read them.**

bagger turns your local Claude Code and Codex transcripts into a searchable,
replayable archive you can read anytime — fully on your own machine.

<p>
  <img src="docs/preview.png" alt="bagger desktop app" width="860" />
</p>

</div>

## What bagger does (MVP)

One focused loop:

1. **Scan** — import local AI conversation transcripts into a local SQLite database.
2. **Search** — full-text search across every conversation (SQLite FTS5 + BM25, CJK-aware).
3. **View** — open any session and read the full conversation: messages, tool calls, and results.

That's the whole product. No accounts, no cloud, no telemetry.

## Quick start

Requires Python 3.12 or newer.

```bash
# Install the CLI and API.
pip install -e ".[web]"

# Initialize the local database and scan existing transcripts.
bagger init
bagger scan

# Search your history, or replay a full session in the terminal.
bagger search "token expiration"
bagger replay <session-id-prefix>
```

The default database is `~/.bagger/bagger.db`. A normal scan imports every
registered source; use `--source claude` or `--source codex` to limit one.

### Optional: desktop app

Prerequisites: Python 3.12+, Node.js 22+, and Rust.

```bash
pip install -e ".[dev,web]"
cd ui
npm install
npm run tauri dev
```

In development, Tauri starts the Python API for you.

## Data sources

| Source | Transcript location | Format |
| --- | --- | --- |
| Claude Code | `~/.claude/projects/` | JSONL session files |
| Codex | `$CODEX_HOME/sessions/` | Rollout JSONL files |

When `CODEX_HOME` is unset, bagger uses `~/.codex/sessions/`. The parser
registry auto-discovers concrete parsers in `bagger/parsers/`, and database
identities are scoped by `(source, id)` so sessions from different tools never
collide.

## CLI

| Command | Purpose |
| --- | --- |
| `bagger init` | Create the data directory and initialize SQLite |
| `bagger scan [--full] [--source …]` | Import sessions incrementally or re-import them fully |
| `bagger search <query>` | Search conversation events with FTS5 / BM25 |
| `bagger replay <session-id>` | Render a complete session in the terminal |
| `bagger export <session-id>` | Export a session as Markdown |
| `bagger doctor` | Check database integrity, FTS, and source discovery |
| `bagger backup <path>` | Create an integrity-checked SQLite backup |
| `bagger rebuild-index` | Rebuild the raw-event FTS5 index |

## REST API

Start the API with:

```bash
bagger serve
```

It listens on `http://127.0.0.1:8723` by default; interactive documentation is at
[`/docs`](http://127.0.0.1:8723/docs). The API binds to loopback by default.

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | Database, FTS, event, and session health |
| `GET /api/sessions` | Paginated sessions with project and source filters |
| `GET /api/sessions/{id}` | Session metadata with prefix matching |
| `GET /api/sessions/{id}/events` | Paginated parsed event blocks |
| `GET /api/sessions/{id}/tree` | Conversation topology and lineage |
| `GET /api/sessions/{id}/export?format=markdown` | Download a session as Markdown |
| `GET /api/search?q=…` | Search raw conversation events |
| `POST /api/scan`, `POST /api/scan/full` | Start a background scan |
| `GET /api/scan/status` | Poll scan progress and outcome |

## Privacy

bagger is local-first:

- Transcript files are read locally and never modified.
- The local database lives under `~/.bagger/` by default.
- There is no telemetry or cloud-sync service.

## Architecture

```text
Claude Code JSONL ─┐
                   ├─ Parser registry ── Sync service ── SQLite + FTS5
Codex rollout JSONL┘                                  │
                                                        ├─ CLI
                                                        ├─ FastAPI
                                                        └─ Tauri + React
```

Dependencies flow downward only:

```text
cli / api  →  services  →  parsers / storage  →  models
```

Key directories:

```text
bagger/
├── api/            FastAPI application and routes
├── cli/            Click commands
├── exporters/      session exports
├── models/         normalized event and session models
├── parsers/        source parser protocol plus Claude and Codex parsers
├── services/       scan, sync, and search services
└── storage/        SQLite, FTS5, migrations, and cache
tests/              pytest suite and transcript fixtures
ui/                 Tauri shell and React desktop application
```

## Development

```bash
pip install -e ".[dev,web]"
pytest tests/ -q
ruff check .
ruff format --check .
```

For frontend changes:

```bash
cd ui
npm test
npm run build
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for project layering, test expectations, and the contribution workflow.

## License

MIT
