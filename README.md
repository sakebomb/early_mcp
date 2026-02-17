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
| `list_activities` | List all activities with IDs, names, and colors |
| `create_activity` | Create a new activity |
| `update_activity` | Update an existing activity's name or color |
| `delete_activity` | Archive/delete an activity |
| `current_tracking` | Get the currently running timer |
| `start_tracking` | Start tracking time for an activity |
| `stop_tracking` | Stop the current tracker |
| `list_time_entries` | Query time entries within a date range |
| `create_time_entry` | Create a manual time entry |
| `delete_time_entry` | Delete a time entry |
| `time_summary` | Aggregate hours by activity for a period |
| `efficiency_report` | Analyze time distribution and detect untracked gaps |
| `billing_report` | Calculate billable hours and cost by activity |
| `explore_api` | Make raw authenticated requests to any EARLY API endpoint |

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
pyproject.toml    # Project config and dependencies
```

## Authentication

The server uses EARLY's developer sign-in flow. It exchanges your API key/secret for a bearer token, caches it in memory, and automatically refreshes on expiry.
