# EARLY MCP Server

An MCP (Model Context Protocol) server that integrates with the [EARLY](https://early.app) (Timeular v4) time tracking API. Gives AI assistants like Claude full access to time tracking, activity management, and analytics.

## Features

- **Activity Management** - Create, update, list, and delete activities
- **Time Tracking** - Start/stop timers, view current tracking status
- **Time Entries** - Query, create, and delete manual time entries
- **Analytics** - Time summaries, efficiency reports with gap detection, and billing reports
- **API Explorer** - Raw authenticated access to any EARLY API endpoint

## Tools

| Tool | Description |
|------|-------------|
| `get_me` | Show the authenticated user's profile |
| `list_tags_and_mentions` | List tags and mentions (IDs used in notes) |
| `list_activities` | List active, inactive and archived activities |
| `create_activity` | Create a new activity |
| `update_activity` | Update an existing activity's name or color |
| `delete_activity` | Archive an activity (entries are kept) |
| `unarchive_activity` | Restore an archived activity |
| `current_tracking` | Get the currently running timer |
| `start_tracking` | Start tracking time for an activity |
| `edit_tracking` | Change the running timer's activity, start time or note |
| `stop_tracking` | Stop the current tracker, creating a time entry |
| `cancel_tracking` | Discard the running timer without creating an entry |
| `list_time_entries` | Query time entries within a date range |
| `get_time_entry` | Get one time entry by ID |
| `create_time_entry` | Create a manual time entry |
| `edit_time_entry` | Change an entry's activity, times or note |
| `delete_time_entry` | Delete a time entry |
| `time_summary` | Aggregate hours by activity for a period |
| `efficiency_report` | Analyze time distribution and detect untracked gaps |
| `billing_report` | Calculate billable hours and cost by activity |
| `explore_api` | Make raw authenticated GET requests to any EARLY API endpoint (writes opt-in) |

## Setup

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- An EARLY developer API key and secret

### Install

```bash
git clone git@github.com:sakebomb/early_mcp.git
cd early_mcp
uv sync
```

### Configuration

Create a `.env` file with your EARLY API credentials:

```
EARLY_API_KEY=your_api_key
EARLY_API_SECRET=your_api_secret
```

Optional settings:

| Variable | Default | Effect |
|----------|---------|--------|
| `EARLY_TIMEZONE` | system timezone | IANA zone (e.g. `America/New_York`) that dates and naive timestamps are read in |
| `EARLY_EXPLORE_ALLOW_WRITES` | unset | Set to `1` to let `explore_api` send POST/PATCH/PUT/DELETE |

### Tool hints

Every tool declares MCP annotations so clients can decide what to confirm. Tools that can lose tracked time are marked destructive: deleting or editing an entry, cancelling a timer, and also creating an entry or stopping a timer, because EARLY splits or removes existing entries that a new one overlaps. `explore_api` is advertised read-only unless writes are enabled.

### Dates and timezones

The EARLY API stores timestamps in UTC without an offset. Tools take dates (`YYYY-MM-DD`) and naive timestamps as local time in `EARLY_TIMEZONE` and convert them to UTC, so a "day" means your local day. Timestamps with an explicit offset (`+01:00`, `Z`) are converted from that offset. Raw entries returned by `list_time_entries` keep EARLY's UTC timestamps; report tools group by local day.

### Claude Code

Add this to your Claude Code MCP settings (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "early": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/early_mcp", "python", "early.py"],
      "env": {
        "EARLY_API_KEY": "your_api_key",
        "EARLY_API_SECRET": "your_api_secret"
      }
    }
  }
}
```

## Project Structure

```
early.py          # MCP server with tool definitions
early_client.py   # API client, auth, and utility functions
tests/            # pytest suite (mocked HTTP; run with `uv run pytest`)
pyproject.toml    # Project config and dependencies
```

## Authentication

The server uses EARLY's developer sign-in flow. It exchanges your API key/secret for a bearer token, caches it in memory, and automatically refreshes on expiry.
