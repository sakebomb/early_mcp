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
| `create_activity` | Create a new activity in a folder (folder ID required) |
| `update_activity` | Update an existing activity's name or color |
| `delete_activity` | Archive an activity (entries are kept) |
| `unarchive_activity` | Restore an archived activity |
| `current_tracking` | Get the currently running timer |
| `start_tracking` | Start tracking time for an activity |
| `edit_tracking` | Change the running timer's activity, start time or note |
| `stop_tracking` | Stop the current tracker, creating a time entry; `round_minutes` snaps it to e.g. quarter hours |
| `cancel_tracking` | Discard the running timer without creating an entry |
| `list_time_entries` | Query time entries within a date range |
| `get_time_entry` | Get one time entry by ID |
| `create_time_entry` | Create a manual time entry |
| `edit_time_entry` | Change an entry's activity, times or note |
| `delete_time_entry` | Delete a time entry |
| `time_summary` | Aggregate hours by activity for a period |
| `efficiency_report` | Analyze time distribution and detect untracked gaps |
| `billing_report` | Calculate billable hours and cost by activity |
| `timesheet` | Roll entries into "Activity: note" rows with rounded hours per local day, optionally for one folder |
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

### Stopping a timer

EARLY rejects a stop less than one minute after the start and discards the timer along with it, so `stop_tracking` checks the timer's age first and leaves a younger one running. With `round_minutes`, both ends of the entry are snapped to the nearest step after the stop. Rounding never reorders times, so entries that did not overlap still do not.

### Command line

`early_cli.py` runs the same tools from a hook or timer, printing JSON:

```bash
uv run python early_cli.py stop --round 15 --folder <folder_id>   # only stops a timer in that folder
uv run python early_cli.py timesheet 2026-10-17 2026-10-30 --folder <folder_id>
```

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
early_cli.py      # Command-line entry for hooks and timers
tests/            # pytest suite (mocked HTTP; run with `uv run pytest`)
pyproject.toml    # Project config and dependencies
```

## Authentication

The server uses EARLY's developer sign-in flow. It exchanges your API key/secret for a bearer token, caches it in memory, and automatically refreshes on expiry.
