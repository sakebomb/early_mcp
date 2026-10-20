"""EARLY time tracking MCP server.

Exposes the EARLY (Timeular v4) API as MCP tools for AI-powered
time tracking, activity management, and API exploration.
"""

import os
from collections import defaultdict
from datetime import timezone
from typing import Any
from urllib.parse import quote

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from early_client import (
    make_early_request,
    now_iso,
    date_range_for_period,
    fetch_entries,
    format_api_ts,
    local_day_hours,
    parse_iso,
    entry_hours,
    rounded_span,
    to_api_ts,
    utc_range,
    utc_to_local,
)

mcp = FastMCP("early")

# Tool behavior hints for MCP clients.
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
ADDITIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
UPDATE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)
# Overwrites or removes tracked time. EARLY also splits or deletes existing
# entries that a new or stopped entry overlaps, so those writes count too.
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True)


def _note(text: str) -> dict[str, Any]:
    return {"text": text, "tags": [], "mentions": []}


def _seg(value: str) -> str:
    """Escape an ID for use as a single URL path segment."""
    return quote(value, safe="")


# --- Account Tools ---


@mcp.tool(annotations=READ_ONLY)
async def get_me() -> dict[str, Any]:
    """Get the authenticated EARLY user's profile (id, name, email)."""
    return await make_early_request("GET", "/me")


@mcp.tool(annotations=READ_ONLY)
async def list_tags_and_mentions() -> dict[str, Any]:
    """List all tags and mentions, including ones from integrations (JIRA, etc.).

    To reference one inside a note, write <{{|t|ID|}}> for a tag or
    <{{|m|ID|}}> for a mention, using the IDs returned here.
    """
    return await make_early_request("GET", "/tags-and-mentions")


# --- Activity Tools ---


@mcp.tool(annotations=READ_ONLY)
async def list_activities() -> dict[str, Any]:
    """List all activities in EARLY.

    Returns active, inactive and archived activities with their IDs, names,
    colors and folder IDs.
    """
    return await make_early_request("GET", "/activities")


@mcp.tool(annotations=ADDITIVE)
async def create_activity(name: str, folder_id: str, color: str = "#4CAF50") -> dict[str, Any]:
    """Create a new activity in EARLY.

    Args:
        name: Name of the activity (e.g. "Deep Work", "Meetings")
        folder_id: Folder to create it in (EARLY requires one); use a folderId from list_activities
        color: Hex color code for the activity (default: green)
    """
    return await make_early_request(
        "POST", "/activities", json_body={"name": name, "color": color, "folderId": folder_id}
    )


@mcp.tool(annotations=UPDATE)
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
    return await make_early_request("PATCH", f"/activities/{_seg(activity_id)}", json_body=body)


@mcp.tool(annotations=UPDATE)
async def delete_activity(activity_id: str) -> dict[str, Any]:
    """Archive an activity in EARLY. Its time entries are kept; undo with unarchive_activity.

    Args:
        activity_id: ID of the activity to archive
    """
    return await make_early_request("DELETE", f"/activities/{_seg(activity_id)}")


@mcp.tool(annotations=UPDATE)
async def unarchive_activity(activity_id: str) -> dict[str, Any]:
    """Restore an archived activity.

    Args:
        activity_id: ID of the archived activity
    """
    return await make_early_request("POST", f"/activities/{_seg(activity_id)}/unarchive")


# --- Tracking Tools ---


@mcp.tool(annotations=READ_ONLY)
async def current_tracking() -> dict[str, Any]:
    """Get the currently running tracking entry, if any.

    Returns the active timer with activity info and start time,
    or an error with "does not exist" if nothing is tracking.
    """
    return await make_early_request("GET", "/tracking")


# Not destructive: EARLY rejects a start while a timer runs (409) rather than
# stopping the running one into an entry (verified live).
@mcp.tool(annotations=ADDITIVE)
async def start_tracking(activity_id: str, note: str | None = None) -> dict[str, Any]:
    """Start tracking time for an activity.

    Args:
        activity_id: ID of the activity to track (use list_activities to find IDs)
        note: Optional note/description for this tracking session
    """
    body: dict[str, Any] = {"startedAt": now_iso()}
    if note:
        body["note"] = _note(note)
    return await make_early_request("POST", f"/tracking/{_seg(activity_id)}/start", json_body=body)


@mcp.tool(annotations=UPDATE)
async def edit_tracking(
    activity_id: str | None = None,
    started_at: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Edit the running tracker: switch activity, move its start time, or set its note.

    Args:
        activity_id: New activity ID (optional)
        started_at: New start time in ISO format; local time unless it has an offset (optional)
        note: New note text; an empty string removes the note (optional).
    """
    body: dict[str, Any] = {}
    if activity_id is not None:
        body["activityId"] = activity_id
    if started_at is not None:
        try:
            body["startedAt"] = to_api_ts(started_at)
        except ValueError as e:
            return {"error": f"Invalid timestamp: {e}"}
    if note is not None:
        # Tags/mentions follow the markers in "text". An empty text clears the
        # note; a null note object is silently ignored (verified live).
        body["note"] = {"text": note}
    if not body:
        return {"error": "No fields to update. Provide activity_id, started_at and/or note."}
    return await make_early_request("PATCH", "/tracking", json_body=body)


@mcp.tool(annotations=DESTRUCTIVE)
async def stop_tracking(round_minutes: int = 0) -> dict[str, Any]:
    """Stop the currently running tracker.

    Returns the completed time entry with start/stop times and duration. The
    entry must be at least 1 minute long; EARLY splits or removes existing
    entries it overlaps.

    Args:
        round_minutes: Snap the entry's start and stop to the nearest multiple of
            this many minutes (e.g. 15); 0 keeps exact times. A span that rounds
            to nothing keeps one step.
    """
    if round_minutes < 0 or (round_minutes and 60 % round_minutes):
        return {"error": "round_minutes must be 0 or divide 60 (e.g. 5, 15, 30)"}
    # EARLY answers a stop under one minute with 400 and also discards the
    # timer (verified live), so check the age first and leave it running.
    tracking = await make_early_request("GET", "/tracking")
    if "error" in tracking:
        return tracking
    stopped_at = now_iso()
    if (parse_iso(stopped_at) - parse_iso(tracking["startedAt"])).total_seconds() < 60:
        return {"error": "Tracker is under 1 minute old; EARLY would discard it. Left running.", "tracking": tracking}
    entry = await make_early_request("POST", "/tracking/stop", json_body={"stoppedAt": stopped_at})
    if "error" in entry or not round_minutes:
        return entry
    d = entry["duration"]
    start, stop = rounded_span(parse_iso(d["startedAt"]), parse_iso(d["stoppedAt"]), round_minutes)
    body = {"startedAt": format_api_ts(start.replace(tzinfo=timezone.utc)), "stoppedAt": format_api_ts(stop.replace(tzinfo=timezone.utc))}
    rounded = await make_early_request("PATCH", f"/time-entries/{_seg(str(entry['id']))}", json_body=body)
    if "error" in rounded:
        return {**rounded, "stopped_entry": entry, "note": "stopped, but rounding failed; entry kept exact times"}
    return rounded


@mcp.tool(annotations=DESTRUCTIVE)
async def cancel_tracking() -> dict[str, Any]:
    """Discard the running tracker without creating a time entry."""
    return await make_early_request("DELETE", "/tracking")


# --- Time Entry Tools ---


@mcp.tool(annotations=READ_ONLY)
async def list_time_entries(start_date: str, end_date: str) -> dict[str, Any]:
    """Query time entries within a date range.

    Dates are local (EARLY_TIMEZONE or the system zone); returned timestamps are UTC.

    Args:
        start_date: Start date in YYYY-MM-DD format (e.g. "2026-02-01")
        end_date: End date in YYYY-MM-DD format, inclusive (e.g. "2026-02-16")
    """
    try:
        start_iso, end_iso = utc_range(start_date, end_date)
    except ValueError as e:
        return {"error": f"Invalid date range: {e}"}
    return await make_early_request("GET", f"/time-entries/{start_iso}/{end_iso}")


@mcp.tool(annotations=READ_ONLY)
async def get_time_entry(entry_id: str) -> dict[str, Any]:
    """Get a single time entry by ID.

    Args:
        entry_id: ID of the time entry
    """
    return await make_early_request("GET", f"/time-entries/{_seg(entry_id)}")


@mcp.tool(annotations=DESTRUCTIVE)
async def create_time_entry(
    activity_id: str,
    started_at: str,
    stopped_at: str,
    note: str | None = None,
) -> dict[str, Any]:
    """Create a manual time entry (at least 1 minute long).

    EARLY splits or removes existing entries that the new one overlaps.

    Args:
        activity_id: ID of the activity
        started_at: Start time in ISO format; local time unless it has an offset (e.g. "2026-02-16T09:00:00")
        stopped_at: Stop time in ISO format; local time unless it has an offset (e.g. "2026-02-16T10:30:00")
        note: Optional note; tags/mentions use the syntax from list_tags_and_mentions
    """
    try:
        body: dict[str, Any] = {
            "activityId": activity_id,
            "startedAt": to_api_ts(started_at),
            "stoppedAt": to_api_ts(stopped_at),
        }
    except ValueError as e:
        return {"error": f"Invalid timestamp: {e}"}
    if note:
        body["note"] = _note(note)
    return await make_early_request("POST", "/time-entries", json_body=body)


@mcp.tool(annotations=DESTRUCTIVE)
async def edit_time_entry(
    entry_id: str,
    activity_id: str | None = None,
    started_at: str | None = None,
    stopped_at: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Edit an existing time entry. Only the fields you pass are changed.

    Changing the activity only works between activities of the same integration.

    Args:
        entry_id: ID of the time entry to edit
        activity_id: New activity ID (optional)
        started_at: New start time in ISO format; local time unless it has an offset (optional)
        stopped_at: New stop time in ISO format; local time unless it has an offset (optional)
        note: New note text, tags/mentions as in list_tags_and_mentions; an empty string removes the note (optional)
    """
    body: dict[str, Any] = {}
    if activity_id is not None:
        body["activityId"] = activity_id
    try:
        if started_at is not None:
            body["startedAt"] = to_api_ts(started_at)
        if stopped_at is not None:
            body["stoppedAt"] = to_api_ts(stopped_at)
    except ValueError as e:
        return {"error": f"Invalid timestamp: {e}"}
    if note is not None:
        # Same shape as edit_tracking: empty text clears, a null note is ignored.
        body["note"] = {"text": note}
    if not body:
        return {"error": "No fields to update. Provide activity_id, started_at, stopped_at and/or note."}
    return await make_early_request("PATCH", f"/time-entries/{_seg(entry_id)}", json_body=body)


@mcp.tool(annotations=DESTRUCTIVE)
async def delete_time_entry(entry_id: str) -> dict[str, Any]:
    """Delete a time entry.

    Args:
        entry_id: ID of the time entry to delete
    """
    return await make_early_request("DELETE", f"/time-entries/{_seg(entry_id)}")


# --- Analysis Tools ---


@mcp.tool(annotations=READ_ONLY)
async def time_summary(period: str = "today") -> dict[str, Any]:
    """Aggregate hours by activity for a time period.

    Args:
        period: One of "today", "yesterday", "week", "last_week", "month", "last_month"
    """
    try:
        start_date, end_date = date_range_for_period(period)
    except ValueError as e:
        return {"error": str(e)}

    entries, error = await fetch_entries(start_date, end_date)
    if error:
        return error
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


@mcp.tool(annotations=READ_ONLY)
async def efficiency_report(start_date: str, end_date: str) -> dict[str, Any]:
    """Analyze time distribution and detect gaps between entries.

    Shows how time was spent, identifies untracked gaps, and provides
    daily breakdowns. Useful for finding productivity patterns.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
    """
    entries, error = await fetch_entries(start_date, end_date)
    if error:
        return error
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
        day = utc_to_local(entry["duration"]["startedAt"]).date().isoformat()
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
                    "gap_start": utc_to_local(sorted_entries[i - 1]["duration"]["stoppedAt"]).isoformat(),
                    "gap_end": utc_to_local(entry["duration"]["startedAt"]).isoformat(),
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


@mcp.tool(annotations=READ_ONLY)
async def billing_report(start_date: str, end_date: str, hourly_rate: float) -> dict[str, Any]:
    """Calculate billable hours and cost by activity.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        hourly_rate: Rate per hour in your currency
    """
    entries, error = await fetch_entries(start_date, end_date)
    if error:
        return error
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


@mcp.tool(annotations=READ_ONLY)
async def timesheet(
    start_date: str,
    end_date: str,
    folder_id: str | None = None,
    round_hours: float = 0.25,
) -> dict[str, Any]:
    """Roll time entries up into timesheet rows: one row per activity and note, hours per local day.

    Entries crossing local midnight are split between the two days. Each day's
    cell is rounded to the nearest round_hours after summing, so short entries
    are not rounded away one by one.

    Args:
        start_date: Start date in YYYY-MM-DD format (local)
        end_date: End date in YYYY-MM-DD format, inclusive (local)
        folder_id: Only include activities in this folder (filter by folder, not by name)
        round_hours: Cell granularity in hours (default 0.25; 0 keeps exact hours)
    """
    if round_hours < 0:
        return {"error": "round_hours must be 0 or positive"}
    entries, error = await fetch_entries(start_date, end_date)
    if error:
        return error

    cells: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for entry in entries:
        activity = entry.get("activity", {})
        if folder_id and activity.get("folderId") != folder_id:
            continue
        note = (entry.get("note") or {}).get("text") or ""
        row = f"{activity.get('name', 'Unknown')}: {note}" if note else activity.get("name", "Unknown")
        for day, hours in local_day_hours(entry).items():
            if start_date <= day.isoformat() <= end_date:
                cells[row][day.isoformat()] += hours

    def _round(h: float) -> float:
        return round(round(h / round_hours) * round_hours, 2) if round_hours else round(h, 2)

    rows = []
    for row, days in sorted(cells.items()):
        rounded = {day: _round(h) for day, h in sorted(days.items()) if _round(h)}
        rows.append({"row": row, "days": rounded, "total": round(sum(rounded.values()), 2)})
    return {
        "start_date": start_date,
        "end_date": end_date,
        "folder_id": folder_id,
        "round_hours": round_hours,
        "rows": rows,
        "total_hours": round(sum(r["total"] for r in rows), 2),
    }


# --- API Explorer ---


def _explore_writes_enabled() -> bool:
    return os.environ.get("EARLY_EXPLORE_ALLOW_WRITES") == "1"


# Hints are fixed at startup, so advertise explore_api as destructive only when
# the server was started with writes enabled.
@mcp.tool(annotations=DESTRUCTIVE if _explore_writes_enabled() else READ_ONLY)
async def explore_api(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Make a raw authenticated request to any EARLY API endpoint.

    Use this to probe undocumented or newly discovered endpoints.
    The base URL is already set — just provide the path. Only GET is allowed
    unless the server runs with EARLY_EXPLORE_ALLOW_WRITES=1; use the dedicated
    tools to change data.

    Args:
        method: HTTP method (GET; POST, PATCH, PUT, DELETE only when writes are enabled)
        path: API path (e.g. "/tracking", "/time-entries/2024-01-01T05:00:00.000/2024-02-01T04:59:59.999")
        body: JSON request body (optional)
        params: Query parameters (optional)
    """
    method = method.upper()
    if method != "GET" and not _explore_writes_enabled():
        return {"error": f"{method} is disabled in explore_api; set EARLY_EXPLORE_ALLOW_WRITES=1 to allow writes"}
    return await make_early_request(method, path, json_body=body, params=params)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
