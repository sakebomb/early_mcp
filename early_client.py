"""EARLY API client — auth, request helpers, and utilities."""

import os
from datetime import datetime, date, timedelta, timezone
from typing import Any

import httpx

# Config from environment
EARLY_API_KEY = os.environ.get("EARLY_API_KEY", "")
EARLY_API_SECRET = os.environ.get("EARLY_API_SECRET", "")
EARLY_BASE_URL = os.environ.get("EARLY_BASE_URL", "https://api.early.app/api/v4")

# Module-level auth token cache
_auth_token: str | None = None


async def _ensure_auth() -> str:
    """Authenticate with EARLY API via developer sign-in and return a token."""
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
                    _auth_token = None
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


def now_iso() -> str:
    """Return current UTC time in EARLY's expected ISO format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000")


def date_range_for_period(period: str) -> tuple[str, str]:
    """Convert a period name to (start_date, end_date) in YYYY-MM-DD format.

    Supported periods: "today", "yesterday", "week" (current), "last_week", "month" (current), "last_month".
    """
    today = date.today()

    if period == "today":
        return str(today), str(today)
    elif period == "yesterday":
        d = today - timedelta(days=1)
        return str(d), str(d)
    elif period == "week":
        start = today - timedelta(days=today.weekday())  # Monday
        return str(start), str(today)
    elif period == "last_week":
        this_monday = today - timedelta(days=today.weekday())
        start = this_monday - timedelta(days=7)
        end = this_monday - timedelta(days=1)
        return str(start), str(end)
    elif period == "month":
        start = today.replace(day=1)
        return str(start), str(today)
    elif period == "last_month":
        first_of_this = today.replace(day=1)
        end = first_of_this - timedelta(days=1)
        start = end.replace(day=1)
        return str(start), str(end)
    else:
        raise ValueError(f"Unknown period: {period}. Use: today, yesterday, week, last_week, month, last_month")


async def fetch_entries(start_date: str, end_date: str) -> list[dict[str, Any]]:
    """Fetch time entries for a date range. Returns the list or empty on error."""
    start_iso = f"{start_date}T00:00:00.000"
    end_iso = f"{end_date}T23:59:59.999"
    result = await make_early_request("GET", f"/time-entries/{start_iso}/{end_iso}")
    if "error" in result:
        return []
    return result.get("timeEntries", [])


def parse_iso(ts: str) -> datetime:
    """Parse an EARLY ISO timestamp."""
    return datetime.fromisoformat(ts)


def entry_hours(entry: dict[str, Any]) -> float:
    """Calculate hours for a single time entry."""
    d = entry.get("duration", {})
    start = parse_iso(d["startedAt"])
    stop = parse_iso(d["stoppedAt"])
    return (stop - start).total_seconds() / 3600
