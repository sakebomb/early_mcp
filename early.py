"""EARLY time tracking MCP server.

Exposes the EARLY (Timeular v4) API as MCP tools for AI-powered
time tracking, activity management, and API exploration.
"""

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("early")

# Config from environment
EARLY_API_KEY = os.environ.get("EARLY_API_KEY", "")
EARLY_BASE_URL = os.environ.get("EARLY_BASE_URL", "https://api.early.app/api/v4")


def _get_auth_headers() -> dict[str, str]:
    """Return auth headers using the API key directly as a Bearer token."""
    if not EARLY_API_KEY:
        raise ValueError("EARLY_API_KEY must be set as an environment variable")
    return {"Authorization": f"Bearer {EARLY_API_KEY}"}


async def make_early_request(
    method: str,
    path: str,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Make an authenticated request to the EARLY API.

    Returns error dicts (not None) so the AI always gets readable output.
    """
    try:
        headers = _get_auth_headers()
    except Exception as e:
        return {"error": f"Authentication failed: {e}"}

    url = f"{EARLY_BASE_URL}{path}" if path.startswith("/") else f"{EARLY_BASE_URL}/{path}"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method,
                url,
                headers=headers,
                json=json_body,
                params=params,
                timeout=30.0,
            )

            if response.status_code == 204:
                return {"success": True, "status": 204}

            response.raise_for_status()
            return response.json()

    except httpx.HTTPStatusError as e:
        body = e.response.text
        return {
            "error": f"HTTP {e.response.status_code}",
            "detail": body[:500],
            "path": path,
        }
    except Exception as e:
        return {"error": str(e), "path": path}


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
