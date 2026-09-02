<div align="center">

# bagger

**Scan local AI coding conversations. Search them. Read them.**

bagger turns your local Claude Code and Codex transcripts into a searchable,
replayable archive you can read anytime — fully on your own machine.

[![CI](https://github.com/lg114/bagger/actions/workflows/ci.yml/badge.svg)](https://github.com/lg114/bagger/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![Status](https://img.shields.io/badge/status-MVP-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

<p>
  <img src="docs/preview.png" alt="bagger desktop app" width="860" />
</p>

</div>

## Contents

- [What bagger does](#what-bagger-does)
- [See it work](#see-it-work)
- [Install](#install)
- [Quick start](#quick-start)
- [Desktop app](#desktop-app)
- [Data sources](#data-sources)
- [How search works](#how-search-works)
- [CLI reference](#cli-reference)
- [REST API](#rest-api)
- [Configuration](#configuration)
- [Security model](#security-model)
- [Data and privacy](#data-and-privacy)
- [Architecture](#architecture)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [Non-goals](#non-goals)
- [License](#license)

## What bagger does

One focused loop:

1. **Scan** — import local AI conversation transcripts into a local SQLite database.
2. **Search** — full-text search across every conversation (SQLite FTS5 + BM25, CJK-aware).
3. **Read** — open any session and read the whole thing: messages, tool calls, and results.

That's the product. No accounts, no cloud, no telemetry.

Three ways to drive it, all reading the same local database:

| Interface | Use it when |
| --- | --- |
| CLI | You live in a terminal and want to grep your own history |
| Desktop app | You want to browse, scroll, and read sessions comfortably |
| REST API | You want to script it or build something on top |

## See it work

```console
$ bagger init
  C:\Users\you\.bagger initialized

$ bagger scan
Scanning all registered sources ...
  71 sessions, 19912 events imported

$ bagger stats

  bagger Statistics
  ──────────────────────────────
  Sessions:     71
  Events:       19912
  User msgs:    6520
  Assistant:    13392
  Tool uses:    4853
  Total tokens: 68,246,035

  Recent sessions:
    2026-08-27  01a04170-980  (99 msgs)   "<recommended_plugins> …"
    2026-08-27  01a031fc-3cd  (110 msgs)  "<recommended_plugins> …"

$ bagger search "FTS5 索引" -n 2

  Found 2 result(s):

  [1] session d34a93dd "了解这个项目"
      2026-06-30 07:11:01  assistant: FTS5 是 SQLite 内置的**全文搜索引擎**（Full-Tex…

  [2] session d34a93dd "了解这个项目"
      2026-06-30 07:10:51  assistant: The user is asking about what FTS5 search upgrade means. This is r...
```

## Install

bagger is not published to PyPI yet — install from source:

```bash
git clone https://github.com/lg114/bagger.git
cd bagger
pip install -e ".[web]"
```

Requires **Python 3.12 or newer**. Extras:

| Extra | Installs | Needed for |
| --- | --- | --- |
| `web` | FastAPI, uvicorn, jieba | REST API, CJK search |
| `dev` | pytest, pytest-cov, ruff, httpx | Contributing |
| `bundle` | PyInstaller | Building the desktop sidecar |

### Platform support

| | CLI + REST API | Desktop app |
| --- | --- | --- |
| Linux | Verified in CI (Ubuntu, Python 3.12 + 3.13) | Not built |
| macOS | Untested (no blocking dependency) | Not built |
| Windows | Untested in CI | Built in CI — Windows MSI, released on `v*` tags |

Only the Windows desktop build is produced today. Everything else runs
cross-platform in principle, but only Linux gets automated test coverage.

## Quick start

```bash
# 1. Create ~/.bagger and initialize the database.
bagger init

# 2. Import every registered source (incremental by default).
bagger scan
#    or: bagger scan --full            # ignore incremental state, re-import
#    or: bagger scan --source claude   # limit to one tool

# 3. Search, then read the full session.
bagger search "token expiration"
bagger replay <session-id-prefix>
```

Session IDs accept any unique **prefix** — `bagger replay d34a93dd` is enough.

The default database is `~/.bagger/bagger.db`. Pass `--source claude` or
`--source codex` to any scan-like command to limit it to one tool.

## Desktop app

Prerequisites: Python 3.12+, Node.js 22+, and Rust.

```bash
pip install -e ".[dev,web]"
cd ui
npm install
npm run tauri dev
```

In development, Tauri starts the Python API for you. Five screens:

| Screen | What it does |
| --- | --- |
| Home | Database overview and recent activity |
| Search | Full-text search with highlighted snippets and a source filter |
| Sessions | Paginated session list, filterable by project and source |
| Session detail | Full conversation: messages, tool calls, and results |
| Scan | Trigger and monitor an import |

## Data sources

| Source | Transcript location | Format |
| --- | --- | --- |
| Claude Code | `~/.claude/projects/` | JSONL session files |
| Codex | `$CODEX_HOME/sessions/` | Rollout JSONL files |

When `CODEX_HOME` is unset, bagger falls back to `~/.codex/sessions/`.

The parser registry auto-discovers concrete parsers in `bagger/parsers/`, and
database identities are scoped by `(source, id)` — so sessions from different
tools never collide even when they share an ID.

## How search works

- **English / ASCII** — SQLite FTS5 with `bm25()` ranking and snippet
  highlighting.
- **CJK** — SQLite's `unicode61` tokenizer does *not* split Han/Kana/Hangul
  characters, so bagger pre-tokenizes CJK text with **jieba** on both the write
  path (index) and the read path (query). Indexed output keeps jieba word
  tokens *plus* every single CJK character, so substring queries still hit.
- **Fallback** — a `LIKE` full-table scan is used only when the FTS5 table is
  missing. A missing jieba does *not* fall back: the CJK query is then matched
  untokenized against a blob-indexed corpus, which returns nothing.

jieba ships in the `web` extra. **Without it, CJK queries silently return
nothing**, because the text was indexed as one opaque blob. bagger warns you
when it detects CJK data with jieba missing; the fix is:

```bash
pip install jieba
bagger rebuild-index     # re-tokenize already-imported data
```

## CLI reference

| Command | Purpose | Options |
| --- | --- | --- |
| `bagger init` | Create `~/.bagger` and initialize SQLite | — |
| `bagger scan` | Import sessions incrementally | `--full`, `--source NAME` |
| `bagger search <query>` | Full-text search | `-s PREFIX`, `-n LIMIT` (default 20) |
| `bagger replay <id>` | Render a session in the terminal | — |
| `bagger stats` | Aggregate counts and token totals | — |
| `bagger export <id>` | Export a session | `--format markdown`, `-o PATH`, `--dir DIR`, `--source NAME` |
| `bagger doctor` | Check DB integrity, FTS, and source discovery | — |
| `bagger backup <path>` | Integrity-checked SQLite backup | — |
| `bagger rebuild-index` | Rebuild the FTS5 index | — |
| `bagger serve` | Start the REST API | `--host`, `--port`, `--reload`, `--no-open`, `--allow-network` |

Notes worth knowing:

- **`bagger backup <path>` refuses to overwrite.** The target must not exist.
  This is deliberate — it stops a scheduled backup from clobbering an older one.
- **`bagger export` prints to stdout** unless you pass `-o` or `--dir`.
- **Every ID argument accepts a prefix**, and `--source` disambiguates when two
  tools share one.
- `bagger --version` prints the installed version.

## REST API

```bash
bagger serve
```

Listens on `http://127.0.0.1:8723` by default; interactive docs at
[`/docs`](http://127.0.0.1:8723/docs). All routes are prefixed with `/api`.

**System**

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | Database, FTS, event and session counts, version |

**Sessions**

| Endpoint | Purpose |
| --- | --- |
| `GET /api/sessions` | Paginated list — `page`, `per_page`, `sort`, `order`, `project`, `source` |
| `GET /api/sources` | Distinct sources present in the store (drives the source facet) |
| `GET /api/sessions/{id}` | Session metadata, prefix-matched; `?source=` disambiguates |
| `GET /api/sessions/{id}/events` | Paginated parsed event blocks — `page`, `per_page`, `source` |
| `GET /api/sessions/{id}/tree` | Conversation topology and lineage |
| `GET /api/sessions/{id}/export` | Download a session — `?format=markdown`, `?source=` |

**Search**

| Endpoint | Purpose |
| --- | --- |
| `GET /api/search` | Full-text search — `q`, `session_id`, `source`, `page`, `per_page` |

**Stats**

| Endpoint | Purpose |
| --- | --- |
| `GET /api/stats` | Aggregate counts, token totals, per-model and per-provider breakdown |
| `GET /api/stats/daily` | Daily event and token counts — `?days=30` |
| `GET /api/stats/tools` | Most-used tools — `?limit=15` |

**Scan**

| Endpoint | Purpose |
| --- | --- |
| `POST /api/scan` | Start an incremental scan in the background |
| `POST /api/scan/full` | Start a full re-scan in the background |
| `GET /api/scan/status` | Poll scan progress and outcome |

## Configuration

Optional. Create `~/.bagger/config.toml` and set only what you want to change:

```toml
bagger_dir = "/path/to/data"        # default: ~/.bagger
api_token = "…"                      # require a Bearer token on /api routes
cors_origins = ["http://127.0.0.1:8723"]
max_request_bytes = 1000000
source_alias = { "claude-foo-proxy" = "anthropic" }
```

| Key | Default | Purpose |
| --- | --- | --- |
| `bagger_dir` | `~/.bagger` | Root for the database, state, exports, and this config |
| `api_token` | `None` | Bearer token required by every `/api` route |
| `cors_origins` | loopback only | Allowed CORS origins — deliberately not a wildcard |
| `max_request_bytes` | `1000000` | Maximum advertised request body size |
| `source_alias` | `{}` | Map a model name to a provider label, overriding the heuristic |

The environment variable **`BAGGER_API_TOKEN`** takes precedence over
`api_token` in the file — handy for CI and shell sessions where you don't want
the secret on disk.

Files under `~/.bagger/`:

| File | What it is |
| --- | --- |
| `bagger.db` | The SQLite database (sessions, events, FTS5 index) |
| `events.jsonl` | Append-only JSONL shadow copy written on every scan |
| `state.json` | Incremental scan offsets (keyed `"source:session_id"`) |
| `config.toml` | Your configuration overrides |

## Security model

bagger can trigger real file scans, so the API is locked down by default:

- **Loopback only.** `bagger serve` refuses non-loopback binds unless you pass
  `--allow-network`, and that additionally requires `api_token` or
  `BAGGER_API_TOKEN`. Without both, it exits with an error.
- **No wildcard CORS.** Defaults to `127.0.0.1` and `localhost` on port 8723.
  An open policy would let any website you visit drive your local agent.
- **Optional token auth.** Set `api_token` to require `Authorization: Bearer …`
- **Secret redaction.** Known secret shapes (passwords, tokens, API keys) are
  redacted before text reaches logs and exports.

## Data and privacy

bagger is local-first:

- Transcript files are read locally and never modified.
- All data lives under `~/.bagger/` by default.
- There is no telemetry, no account, and no cloud sync.
- Network access is never required to scan, search, or read.

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

Layer responsibilities:

| Directory | Responsibility |
| --- | --- |
| `bagger/models` | Normalized event and session models |
| `bagger/parsers` | Parser protocol plus the Claude and Codex implementations |
| `bagger/storage` | SQLite, FTS5, migrations, and the stats TTL cache |
| `bagger/services` | Scan, sync, search, and replay orchestration |
| `bagger/exporters` | Markdown and JSONL export backends |
| `bagger/api` | FastAPI application, routes, and scan state |
| `bagger/cli` | Click commands |
| `ui` | Tauri shell and React desktop application |
| `tests` | pytest suite and transcript fixtures |

For the full file tree and the layering rules that CI enforces, see
[CONTRIBUTING.md](CONTRIBUTING.md).

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

See [CONTRIBUTING.md](CONTRIBUTING.md) for project layering, test expectations,
and the contribution workflow.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Database is empty — run 'bagger scan' first.` | Scanned nothing yet | `bagger scan` |
| CJK queries return nothing | jieba missing | `pip install jieba && bagger rebuild-index` |
| `FTS5 not enabled` in `bagger doctor` | Index never built | `bagger rebuild-index` |
| `Backup target already exists` | `backup` never overwrites | Choose a new path |
| `Refusing non-loopback binding` | Non-loopback bind without a token | Add `--allow-network` **and** set `BAGGER_API_TOKEN` |
| `No transcripts found` | Wrong source path | Run `bagger doctor` to see what was discovered |
| `No session found matching: …` | Prefix not unique or wrong | Use a longer prefix, or check `bagger stats` |

To restore from a backup, stop bagger and copy the file back over
`~/.bagger/bagger.db`.

## Non-goals

bagger is deliberately small. It does **not** do:

- Cloud sync, accounts, or any network dependency for the core loop
- Semantic or embedding-based retrieval — search is lexical FTS5 only
- Memory consolidation, summarization, or agent-style recall
- Live file watching — imports are explicit (`bagger scan`) or API-triggered
- Cross-machine database merge

## License

MIT
