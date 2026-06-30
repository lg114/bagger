# bagger

> AI Coding Agent Data Collector — sync Claude Code transcripts into a searchable local database with a web UI.

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
# 1. Install
pip install -e .

# 2. Initialize
bagger init

# 3. Import your existing sessions
bagger scan

# 4. Search (CLI)
bagger search "token expiration"
bagger search "登录" -s abc123     # filter by session prefix

# 5. Replay a session
bagger replay abc123               # supports prefix matching

# 6. Start the web API
pip install -e ".[web]"
bagger serve                       # → http://localhost:8723/docs
```

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

## REST API

`bagger serve` starts a FastAPI server on `http://localhost:8723` with interactive Swagger docs.

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | Database status, event/session counts, FTS state |
| `GET /api/sessions?page=1&per_page=50` | Paginated session list |
| `GET /api/sessions/{id}` | Session metadata |
| `GET /api/sessions/{id}/events` | All events for a session (content_blocks parsed) |

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
       CLI      REST API    Tauri
     (Click)   (FastAPI)   (coming)
```

### Search: FTS5 + LIKE hybrid

- **English/ASCII queries** → SQLite FTS5 with BM25 ranking and `<mark>` snippet highlighting
- **Chinese/CJK queries** → LIKE fallback (FTS5 unicode61 can't segment CJK)
- English search is fast and ranked; Chinese search is exhaustive but guarantees no misses

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
pytest tests/ -v            # 28 tests
```

## License

MIT
