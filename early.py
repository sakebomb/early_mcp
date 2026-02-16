"""EARLY time tracking MCP server.

Exposes the EARLY (Timeular v4) API as MCP tools for AI-powered
time tracking, activity management, and API exploration.
"""

from collections import defaultdict
from typing import Any

from mcp.server.fastmcp import FastMCP

from early_client import (
    make_early_request,
    now_iso,
    date_range_for_period,
    fetch_entries,
    parse_iso,
    entry_hours,
)

mcp = FastMCP("early")


# --- Activity Tools ---


@mcp.tool()
async def list_activities() -> dict[str, Any]:
    """List all activities in EARLY.

    Returns the full list of activities with their IDs, names, colors, etc.
    """
    return await make_early_request("GET", "/activities")


@mcp.tool()
async def create_activity(name: str, color: str = "#4CAF50") -> dict[str, Any]:
    """Create a new activity in EARLY.

    Args:
        name: Name of the activity (e.g. "Deep Work", "Meetings")
        color: Hex color code for the activity (default: green)
    """
    return await make_early_request("POST", "/activities", json_body={"name": name, "color": color})


@mcp.tool()
async def update_activity(activity_id: str, name: str | None = None, color: str | None = None) -> dict[str, Any]:
    """Update an existing activity in EARLY.

    Args:
        activity_id: ID of the activity to update
        name: New name for the activity (optional)
        color: New hex color code (optional)
    """
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if color is not None:
        body["color"] = color
    if not body:
        return {"error": "No fields to update. Provide name and/or color."}
    return await make_early_request("PATCH", f"/activities/{activity_id}", json_body=body)


@mcp.tool()
async def delete_activity(activity_id: str) -> dict[str, Any]:
    """Archive/delete an activity in EARLY.

    Args:
        activity_id: ID of the activity to archive
    """
    return await make_early_request("DELETE", f"/activities/{activity_id}")


# --- Tracking Tools ---


@mcp.tool()
async def current_tracking() -> dict[str, Any]:
    """Get the currently running tracking entry, if any.

    Returns the active timer with activity info and start time,
    or an error with "does not exist" if nothing is tracking.
    """
    return await make_early_request("GET", "/tracking")


@mcp.tool()
async def start_tracking(activity_id: str, note: str | None = None) -> dict[str, Any]:
    """Start tracking time for an activity.

    Args:
        activity_id: ID of the activity to track (use list_activities to find IDs)
        note: Optional note/description for this tracking session
    """
    body: dict[str, Any] = {"startedAt": now_iso()}
    if note:
        body["note"] = {"text": note, "tags": [], "mentions": []}
    return await make_early_request("POST", f"/tracking/{activity_id}/start", json_body=body)


@mcp.tool()
async def stop_tracking() -> dict[str, Any]:
    """Stop the currently running tracker.

    Returns the completed time entry with start/stop times and duration.
    """
    return await make_early_request("POST", "/tracking/stop", json_body={"stoppedAt": now_iso()})


# --- Time Entry Tools ---


@mcp.tool()
async def list_time_entries(start_date: str, end_date: str) -> dict[str, Any]:
    """Query time entries within a date range.

    Args:
        start_date: Start date in YYYY-MM-DD format (e.g. "2026-02-01")
        end_date: End date in YYYY-MM-DD format (e.g. "2026-02-16")
    """
    start_iso = f"{start_date}T00:00:00.000"
    end_iso = f"{end_date}T23:59:59.999"
    return await make_early_request("GET", f"/time-entries/{start_iso}/{end_iso}")


@mcp.tool()
async def create_time_entry(
    activity_id: str,
    started_at: str,
    stopped_at: str,
    note: str | None = None,
) -> dict[str, Any]:
    """Create a manual time entry.

    Args:
        activity_id: ID of the activity
        started_at: Start time in ISO format (e.g. "2026-02-16T09:00:00.000")
        stopped_at: Stop time in ISO format (e.g. "2026-02-16T10:30:00.000")
        note: Optional note/description for this entry
    """
    body: dict[str, Any] = {
        "activityId": activity_id,
        "startedAt": started_at,
        "stoppedAt": stopped_at,
    }
    if note:
        body["note"] = {"text": note, "tags": [], "mentions": []}
    return await make_early_request("POST", "/time-entries", json_body=body)


@mcp.tool()
async def delete_time_entry(entry_id: str) -> dict[str, Any]:
    """Delete a time entry.

    Args:
        entry_id: ID of the time entry to delete
    """
    return await make_early_request("DELETE", f"/time-entries/{entry_id}")


# --- Analysis Tools ---


@mcp.tool()
async def time_summary(period: str = "today") -> dict[str, Any]:
    """Aggregate hours by activity for a time period.

    Args:
        period: One of "today", "yesterday", "week", "last_week", "month", "last_month"
    """
    try:
        start_date, end_date = date_range_for_period(period)
    except ValueError as e:
        return {"error": str(e)}

    entries = await fetch_entries(start_date, end_date)
    if not entries:
        return {"period": period, "start_date": start_date, "end_date": end_date, "total_hours": 0, "activities": [], "entry_count": 0}

    by_activity: dict[str, dict[str, Any]] = defaultdict(lambda: {"hours": 0.0, "entries": 0})
    total = 0.0

    for entry in entries:
        name = entry.get("activity", {}).get("name", "Unknown")
        hours = entry_hours(entry)
        by_activity[name]["hours"] += hours
        by_activity[name]["entries"] += 1
        total += hours

    activities = [
        {"name": name, "hours": round(data["hours"], 2), "entries": data["entries"], "percent": round(data["hours"] / total * 100, 1) if total else 0}
        for name, data in sorted(by_activity.items(), key=lambda x: x[1]["hours"], reverse=True)
    ]

    return {
        "period": period,
        "start_date": start_date,
        "end_date": end_date,
        "total_hours": round(total, 2),
        "entry_count": len(entries),
        "activities": activities,
    }


@mcp.tool()
async def efficiency_report(start_date: str, end_date: str) -> dict[str, Any]:
    """Analyze time distribution and detect gaps between entries.

    Shows how time was spent, identifies untracked gaps, and provides
    daily breakdowns. Useful for finding productivity patterns.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
    """
    entries = await fetch_entries(start_date, end_date)
    if not entries:
        return {"start_date": start_date, "end_date": end_date, "total_hours": 0, "tracked_days": 0, "gaps": [], "daily_breakdown": []}

    # Sort entries by start time
    sorted_entries = sorted(entries, key=lambda e: e["duration"]["startedAt"])

    total = 0.0
    by_day: dict[str, float] = defaultdict(float)
    gaps = []

    for i, entry in enumerate(sorted_entries):
        hours = entry_hours(entry)
        total += hours
        day = entry["duration"]["startedAt"][:10]
        by_day[day] += hours

        # Detect gaps > 15 minutes between consecutive entries
        if i > 0:
            prev_stop = parse_iso(sorted_entries[i - 1]["duration"]["stoppedAt"])
            curr_start = parse_iso(entry["duration"]["startedAt"])
            gap_minutes = (curr_start - prev_stop).total_seconds() / 60
            if gap_minutes > 15:
                gaps.append({
                    "after": sorted_entries[i - 1].get("activity", {}).get("name", "Unknown"),
                    "before": entry.get("activity", {}).get("name", "Unknown"),
                    "gap_start": sorted_entries[i - 1]["duration"]["stoppedAt"],
                    "gap_end": entry["duration"]["startedAt"],
                    "gap_minutes": round(gap_minutes, 1),
                })

    daily_breakdown = [
        {"date": day, "hours": round(hours, 2)}
        for day, hours in sorted(by_day.items())
    ]

    tracked_days = len(by_day)
    avg_per_day = round(total / tracked_days, 2) if tracked_days else 0

    return {
        "start_date": start_date,
        "end_date": end_date,
        "total_hours": round(total, 2),
        "tracked_days": tracked_days,
        "avg_hours_per_day": avg_per_day,
        "entry_count": len(entries),
        "gap_count": len(gaps),
        "gaps": gaps[:20],  # Cap at 20 to avoid huge responses
        "daily_breakdown": daily_breakdown,
    }


@mcp.tool()
async def billing_report(start_date: str, end_date: str, hourly_rate: float) -> dict[str, Any]:
    """Calculate billable hours and cost by activity.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        hourly_rate: Rate per hour in your currency
    """
    entries = await fetch_entries(start_date, end_date)
    if not entries:
        return {"start_date": start_date, "end_date": end_date, "hourly_rate": hourly_rate, "total_hours": 0, "total_cost": 0, "activities": []}

    by_activity: dict[str, float] = defaultdict(float)
    total = 0.0

    for entry in entries:
        name = entry.get("activity", {}).get("name", "Unknown")
        hours = entry_hours(entry)
        by_activity[name] += hours
        total += hours

    activities = [
        {"name": name, "hours": round(hours, 2), "cost": round(hours * hourly_rate, 2)}
        for name, hours in sorted(by_activity.items(), key=lambda x: x[1], reverse=True)
    ]

    return {
        "start_date": start_date,
        "end_date": end_date,
        "hourly_rate": hourly_rate,
        "total_hours": round(total, 2),
        "total_cost": round(total * hourly_rate, 2),
        "entry_count": len(entries),
        "activities": activities,
    }


# --- API Explorer ---


@mcp.tool()
async def explore_api(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Make a raw authenticated request to any EARLY API endpoint.

    Use this to probe undocumented or newly discovered endpoints.
    The base URL is already set — just provide the path.

    Args:
        method: HTTP method (GET, POST, PATCH, DELETE, PUT)
        path: API path (e.g. "/tracking", "/time-entries/2024-01-01/2024-01-31")
        body: JSON request body (optional)
        params: Query parameters (optional)
    """
    return await make_early_request(method, path, json_body=body, params=params)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
