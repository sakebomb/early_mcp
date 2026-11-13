# AGENTS.md

early_mcp is an MCP server and CLI for the EARLY time tracker (Timeular v4 API). See its row in the
[Component Map](https://github.com/sakebomb/homelab-blueprint/blob/main/Component%20Map.md).
Tools, settings and CLI usage: [README.md](README.md).
This file is a map, not the full story. Details live in the docs it names, so open the named doc
before answering from the map.

## Where to look
| You need | Look in |
|---|---|
| MCP tool definitions, overlap refusal | `early.py`; tool hints and stop-timer rules in `README.md` |
| API client, auth, date and timezone helpers | `early_client.py`; dates and timezones in `README.md` |
| CLI for hooks and timers | `early_cli.py`; usage in `README.md` ("Command line") |
| Tests (mocked HTTP) | `tests/`; overlap rules in `tests/test_overlaps.py` |
| Dependencies and pytest config | `pyproject.toml`, `uv.lock` |
| PR review workflow | `.github/workflows/claude.yml` |

## Build and test
There is no test CI: the only workflow, `claude.yml`, reviews PRs. Run the tests by hand; they
mock all HTTP and need no credentials:
```bash
uv sync
uv run pytest
```
The server reads its credentials from the environment, set in the MCP client's `env` block
(`README.md`, "Claude Code"; the code does not load a `.env` file), by name only: `EARLY_API_KEY`,
`EARLY_API_SECRET`. Optional: `EARLY_BASE_URL`, `EARLY_TIMEZONE`, `EARLY_EXPLORE_ALLOW_WRITES`.

## Git
Branch from `origin/main` in your own worktree (`feat/`, `fix/`, `refactor/`, `test/`); the
main checkout may hold someone's in-progress branch. One PR per change, squash-merged by the
operator.

## Where it runs
An MCP server over stdio, started by the client with `uv run --directory <checkout> python early.py`
(registration is in README.md, "Claude Code"). `early_cli.py` runs the same way for hooks. A merged
change takes effect when the operator pulls `main` in the checkout the client points at and the
client restarts the server.

## Never
- Call the live EARLY API from tests or while investigating. It holds real time entries.
- Bypass the overlap refusal in `early.py`: a write that overlaps existing entries is refused
  unless `overwrite` is set. Do not set it by default or to get a test or command past the check.
- Commit credentials or a `.env` file.
- Send POST/PATCH/PUT/DELETE through `explore_api` while testing.
