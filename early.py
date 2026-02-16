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
EARLY_API_SECRET = os.environ.get("EARLY_API_SECRET", "")
EARLY_BASE_URL = os.environ.get("EARLY_BASE_URL", "https://api.early.app/api/v4")

# Module-level auth token cache
_auth_token: str | None = None


async def _ensure_auth() -> str:
    """Authenticate with EARLY API via developer sign-in and return a token.

    Caches the token at module level. Re-authenticates if no token is cached.
    """
    global _auth_token
    if _auth_token:
        return _auth_token

    if not EARLY_API_KEY or not EARLY_API_SECRET:
        raise ValueError(
            "EARLY_API_KEY and EARLY_API_SECRET must be set as environment variables"
        )

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{EARLY_BASE_URL}/developer/sign-in",
            json={"apiKey": EARLY_API_KEY, "apiSecret": EARLY_API_SECRET},
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()

    token = data.get("token") or data.get("accessToken")
    if not token:
        raise ValueError(f"No token in auth response. Keys returned: {list(data.keys())}")

    _auth_token = token
    return _auth_token


async def make_early_request(
    method: str,
    path: str,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Make an authenticated request to the EARLY API.

    Automatically re-authenticates once on 401 (expired token).
    Returns error dicts (not None) so the AI always gets readable output.
    """
    global _auth_token

    for attempt in range(2):
        try:
            token = await _ensure_auth()
        except Exception as e:
            return {"error": f"Authentication failed: {e}"}

        headers = {"Authorization": f"Bearer {token}"}
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

                if response.status_code == 401 and attempt == 0:
                    _auth_token = None  # Force re-auth on next attempt
                    continue

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

    return {"error": "Request failed after retry", "path": path}


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
