# bagger

> AI Coding Agent Data Collector — sync Claude Code transcripts into a searchable local database.

bagger reads the JSONL transcripts that Claude Code writes to `~/.claude/projects/` and turns them into a queryable SQLite database with full-text search and session replay. Think of it as your AI coding memory layer.

## Why

Claude Code already records everything you and the assistant say — every prompt, response, tool call, and thinking block. But those JSONL files sit in `~/.claude/projects/` as raw append-only logs. bagger makes them searchable.

```
~/.claude/projects/<hash>/<uuid>.jsonl    # raw transcript
          │
          ▼
       bagger
          │
          ▼
    ~/.bagger/bagger.db                    # searchable SQLite
```

## Quick start

```bash
# 1. Install
pip install -e .

# 2. Initialize
bagger init

# 3. Import your existing sessions
bagger scan

# 4. Search
bagger search "token expiration"
bagger search "登录" -s abc123     # filter by session prefix

# 5. Replay a session
bagger replay abc123               # supports prefix matching
```

## Commands

| Command | Description |
|---------|-------------|
| `bagger init` | Create `~/.bagger/` and initialize the database |
| `bagger scan` | Import all Claude Code sessions (use `--full` to re-import) |
| `bagger watch` | Continuously sync new events as you chat with Claude Code |
| `bagger search <query>` | Full-text search across all conversations |
| `bagger replay <session_id>` | Replay an entire conversation in the terminal |
| `bagger stats` | Show session and event counts |
| `bagger doctor` | Run diagnostics on the database and Claude config |

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
          ┌─────────┴─────────┐
          ▼                   ▼
     SQLite + LIKE      ~/.bagger/events.jsonl
          │              (raw backup)
          │
          ├──────────┐──────────┐
          ▼          ▼          ▼
       search     replay     stats
```

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
pytest tests/ -v            # 14 tests
```

## License

MIT
