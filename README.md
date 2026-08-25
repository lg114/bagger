<div align="center">

# bagger

**A local memory layer for AI coding agents.**

Turn local Claude Code and Codex transcripts into a searchable, replayable, and reusable knowledge base.

<p>
  <img src="docs/preview.png" alt="bagger desktop app" width="860" />
</p>

</div>

## Why bagger?

AI coding sessions contain decisions, fixes, explanations, and hard-won context—but that history is usually scattered across transcript files. `bagger` keeps it local, makes it searchable, and turns useful discoveries into structured memories.

| Conversation history | Structured memory |
| --- | --- |
| Find the exact place where something was said | Capture what was learned or decided |
| Replay complete sessions and tool activity | Retrieve facts, preferences, decisions, and lessons |
| Search with SQLite FTS5 and BM25 | Combine keyword and semantic search |
| Keep Claude Code and Codex data isolated | Preserve source and session provenance |

## Highlights

- **Local-first:** transcripts and the SQLite database stay on your machine by default.
- **Multi-source:** imports Claude Code JSONL and Codex rollout JSONL through a parser registry.
- **Searchable:** uses SQLite FTS5, BM25 ranking, and optional CJK-aware tokenization.
- **Replayable:** renders text, thinking, tool calls, and tool results from complete sessions.
- **Incremental:** scans append-only transcripts and watches source folders for new events.
- **Memory-aware:** consolidates conversations into facts, preferences, decisions, and lessons.
- **Flexible retrieval:** supports local FTS, vector search, and hybrid reciprocal-rank fusion.
- **Multiple interfaces:** includes a CLI, loopback-by-default FastAPI service, and Tauri desktop app.

## Quick start

Requires Python 3.12 or newer.

```bash
# Install the CLI and API dependencies.
pip install -e ".[web]"

# Initialize the local database and import existing transcripts.
bagger init
bagger scan

# Search, replay, or export a session.
bagger search "token expiration"
bagger replay <session-id-prefix>
bagger export <session-id-prefix>

# Start the local API and Swagger UI.
bagger serve
```

The default database is `~/.bagger/bagger.db`. A normal scan imports all registered sources; use `--source claude` or `--source codex` to limit an operation.

### Optional: desktop app

Prerequisites: Python 3.12+, Node.js 22+, and Rust.

```bash
pip install -e ".[dev,web]"
cd ui
npm install
npm run tauri dev
```

In development, Tauri starts the Python API. Reload is enabled on macOS/Linux; Windows runs without reload to avoid extra console windows.

## Data sources

| Source | Transcript location | Format |
| --- | --- | --- |
| Claude Code | `~/.claude/projects/` | JSONL session files |
| Codex | `$CODEX_HOME/sessions/` | Rollout JSONL files |

When `CODEX_HOME` is unset, bagger uses `~/.codex/sessions/`. The parser registry auto-discovers concrete parsers in `bagger/parsers/`, and database identities are scoped by `(source, id)` so sessions from different tools cannot collide.

## CLI

### Import and inspect

| Command | Purpose |
| --- | --- |
| `bagger init` | Create the data directory and initialize SQLite |
| `bagger scan [--full] [--source …]` | Import sessions incrementally or re-import them fully |
| `bagger watch [--source …] [--debounce …] [--rescan …]` | Watch transcript folders and sync new events |
| `bagger search <query>` | Search raw conversation events with FTS5/BM25 |
| `bagger replay <session-id>` | Render a complete session in the terminal |
| `bagger export <session-id>` | Export a session as Markdown |
| `bagger stats` | Show session, event, token, and tool-use totals |
| `bagger doctor` | Check database integrity, FTS, and source discovery |
| `bagger backup <path>` | Create an integrity-checked SQLite backup |
| `bagger rebuild-index` | Rebuild the raw-event FTS5 index |

### Memory and retrieval

| Command | Purpose |
| --- | --- |
| `bagger consolidate` | Distill new conversation content into structured memories |
| `bagger memories [topic]` | Browse consolidated memory records |
| `bagger memories-dedup` | Preview or merge near-duplicate records |
| `bagger memories-stats` | Show memory-corpus statistics |
| `bagger embed` | Create embeddings for memory records |
| `bagger recall <query>` | Retrieve memories with FTS, vector, or hybrid search |

### Examples

```bash
bagger scan --source codex
bagger search "登录" --session abc123
bagger consolidate --dry-run
bagger consolidate --mock                 # offline smoke test
bagger embed --provider remote
bagger recall "how we handle migrations" --mode hybrid
bagger memories-dedup --dry-run
```

`consolidate` requires `BAGGER_LLM_API_KEY` or `llm_api_key` in the config unless you use `--dry-run` or `--mock`. FTS-only recall works offline. Vector and hybrid recall require an embedding provider.

## Structured memory

Raw transcript search answers **“where was this said?”**. Consolidation adds a curated memory layer that answers **“what did we learn or decide?”**.

```text
Conversation events
        │
        ▼
  Consolidator ──► facts, preferences, decisions, lessons
        │
        ├──────────► local FTS / BM25
        ├──────────► remote or fake embeddings
        └──────────► hybrid retrieval
```

Each memory retains source and session provenance. Records can be archived and restored; archived records are excluded from browsing and retrieval by default.

Memory retrieval modes:

- `fts` — local BM25 keyword search
- `vector` — semantic nearest-neighbour search over embeddings
- `hybrid` — FTS and vector rankings combined with reciprocal-rank fusion

Consolidation and embeddings use configurable OpenAI-compatible endpoints. The defaults target Zhipu AI's compatible API, but the URL, model, and keys can be overridden.

## REST API

Start the API with:

```bash
bagger serve
```

By default it listens on `http://127.0.0.1:8723`; interactive documentation is available at [`/docs`](http://127.0.0.1:8723/docs).

The API binds to loopback by default. Only widen `cors_origins` for browser origins you trust, because scan endpoints can read local transcript folders.

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | Database, FTS, event, and session health |
| `GET /api/sessions` | Paginated sessions with project and source filters |
| `GET /api/sessions/{id}` | Session metadata with prefix matching |
| `GET /api/sessions/{id}/events` | Paginated parsed event blocks |
| `GET /api/sessions/{id}/tree` | Conversation topology and lineage |
| `GET /api/sessions/{id}/export?format=markdown` | Download a session as Markdown |
| `GET /api/search?q=…` | Search raw conversation events |
| `GET /api/memories` | Browse memories by source, type, and archive state |
| `PATCH /api/memories/{id}` | Archive or restore a memory |
| `GET /api/memories/search?q=…&mode=…` | FTS, vector, or hybrid memory retrieval |
| `GET /api/stats` | Aggregate statistics |
| `GET /api/stats/daily` | Daily time-series statistics |
| `GET /api/stats/tools` | Tool-use statistics |
| `POST /api/scan`, `POST /api/scan/full` | Start a background scan |
| `GET /api/scan/status` | Poll scan progress and outcome |

## Desktop app

The desktop client is built with Tauri, React, Vite, and Tailwind. It provides dashboards, conversation and project browsing, raw search, memory browsing/retrieval, analytics, import status, and settings.

### Production build

The current production installer configuration targets Windows MSI and bundles the Python API as a PyInstaller sidecar.

Use a clean environment so development-only packages are not bundled:

```powershell
python -m venv .venv-bundle
.\.venv-bundle\Scripts\Activate.ps1
pip install -e ".[web,bundle]"
python scripts/build-backend.py
cd ui
npm run tauri build
```

On macOS/Linux, activate the environment with `source .venv-bundle/bin/activate`. If PowerShell blocks the activation script, use the virtual-environment interpreter directly:

```powershell
.\.venv-bundle\Scripts\python.exe -m pip install -e ".[web,bundle]"
```

macOS/Linux packaging requires platform-specific Tauri bundle and sidecar configuration.

## Configuration

Everything works with defaults. To override them, create `~/.bagger/config.toml`:

```toml
# Store bagger data elsewhere.
bagger_dir = "D:/data/bagger"

# Keep the local API constrained to trusted origins.
cors_origins = ["http://127.0.0.1:8723", "http://localhost:8723"]

# Optional API authentication and request-size guard.
# api_token = "use-a-long-random-token"
# max_request_bytes = 1000000

# Redact common credential-shaped strings before remote calls (default: true).
remote_redact_secrets = true

# Consolidation LLM (or set BAGGER_LLM_API_KEY in the environment).
llm_base_url = "https://open.bigmodel.cn/api/paas/v4"
llm_model = "glm-4-flash"
# llm_api_key = "..."

# Embedding provider (or set BAGGER_EMBEDDING_API_KEY).
embedding_provider = "remote"
embedding_base_url = "https://open.bigmodel.cn/api/paas/v4"
embedding_model = "embedding-3"

# Override provider detection for a proxy or custom backend.
source_alias = { "claude-mimo-proxy" = "xiaomi" }
```

Environment variables take precedence over matching config values for API keys and provider settings. Common supported environment variables include:

```text
BAGGER_API_TOKEN
BAGGER_LLM_API_KEY
BAGGER_LLM_BASE_URL
BAGGER_LLM_MODEL
BAGGER_EMBEDDING_API_KEY
BAGGER_EMBEDDING_BASE_URL
BAGGER_EMBEDDING_MODEL
BAGGER_EMBEDDING_PROVIDER
BAGGER_REMOTE_REDACT_SECRETS
```

## Privacy and security

bagger is local-first:

- Transcript files are read locally and never modified.
- The local database is stored under `~/.bagger/` by default.
- There is no telemetry or cloud-sync service.
- Consolidation and remote embeddings are optional network operations.
- Only content selected for a remote request is sent to the configured provider.
- Common credential-shaped strings are redacted before remote LLM and embedding calls by default.

To expose the API beyond the local machine, set `BAGGER_API_TOKEN` or `api_token` in the config, then explicitly allow non-loopback binding:

```bash
bagger serve --allow-network --host 0.0.0.0
```

Requests must include `Authorization: Bearer <token>`. If a browser frontend connects from another origin, add that trusted origin to `cors_origins` as well.

When using the desktop frontend with an authenticated API, provide the same token at build time with `VITE_API_TOKEN`. This embeds the token in the frontend bundle, so use it only for a trusted local package—not as a secret in a publicly distributed web frontend.

## Architecture

```text
Claude Code JSONL ─┐
                   ├─ Parser registry ── Sync service ── SQLite + FTS5
Codex rollout JSONL┘                                  │
                                                        ├─ CLI
                                                        ├─ FastAPI
                                                        └─ Tauri + React

SQLite memories ── Consolidator ── structured records ── FTS / embeddings / hybrid recall
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
├── consolidation/  memory extraction, validation, normalization, deduplication
├── embedding/      embedding providers
├── exporters/      session exports
├── models/         normalized event and session models
├── parsers/        source parser protocol plus Claude and Codex parsers
├── services/       scan, sync, watch, search, replay, and embedding services
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

## Roadmap

- [x] Multi-source ingestion for Claude Code and Codex
- [x] CJK-aware full-text search and Markdown export
- [x] Desktop app and production sidecar build
- [x] Structured memory extraction, deduplication, embeddings, and hybrid recall
- [ ] Additional source parsers, including Cursor and Gemini
- [ ] Additional export formats

## License

MIT
