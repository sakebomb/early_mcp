"""EARLY API client — auth, request helpers, and utilities."""

import os
from datetime import datetime, date, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

import httpx

# Config from environment
EARLY_API_KEY = os.environ.get("EARLY_API_KEY", "")
EARLY_API_SECRET = os.environ.get("EARLY_API_SECRET", "")
EARLY_BASE_URL = os.environ.get("EARLY_BASE_URL", "https://api.early.app/api/v4")

# EARLY API timestamps are UTC with no offset suffix, millisecond precision.
API_TS_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"

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


def local_tz() -> tzinfo | None:
    """Timezone that dates are interpreted in: EARLY_TIMEZONE, else None (system local)."""
    name = os.environ.get("EARLY_TIMEZONE")
    return ZoneInfo(name) if name else None


def format_api_ts(dt: datetime) -> str:
    """Format an aware datetime as an EARLY API (UTC) timestamp."""
    return dt.astimezone(timezone.utc).strftime(API_TS_FORMAT)[:-3]


def local_to_utc(local: datetime) -> datetime:
    """Interpret a naive local datetime in local_tz() and return it in UTC.

    With no EARLY_TIMEZONE, naive astimezone() applies the system zone's rules
    for that specific date, so DST is handled per day.
    """
    tz = local_tz()
    aware = local.replace(tzinfo=tz) if tz else local.astimezone()
    return aware.astimezone(timezone.utc)


def utc_to_local(ts: str) -> datetime:
    """Convert an EARLY API (UTC) timestamp to an aware local datetime."""
    utc = parse_iso(ts).replace(tzinfo=timezone.utc)
    tz = local_tz()
    return utc.astimezone(tz) if tz else utc.astimezone()


def to_api_ts(ts: str) -> str:
    """Normalize a user-supplied ISO timestamp to an EARLY API timestamp.

    A timestamp with an offset (or "Z") is converted from that offset; a naive
    one is taken as local time.
    """
    dt = datetime.fromisoformat(ts)
    return format_api_ts(dt if dt.tzinfo else local_to_utc(dt))


def utc_range(start_date: str, end_date: str) -> tuple[str, str]:
    """Convert inclusive local dates (YYYY-MM-DD) to EARLY API range bounds in UTC."""
    start = local_to_utc(datetime.fromisoformat(start_date))
    end = local_to_utc(datetime.fromisoformat(end_date) + timedelta(days=1))
    return format_api_ts(start), format_api_ts(end - timedelta(milliseconds=1))


def today_local() -> date:
    """Today's date in local_tz()."""
    return datetime.now(local_tz()).date()


def date_range_for_period(period: str, today: date | None = None) -> tuple[str, str]:
    """Convert a period name to local (start_date, end_date) in YYYY-MM-DD format.

    Supported periods: "today", "yesterday", "week" (current), "last_week", "month" (current), "last_month".
    """
    today = today or today_local()

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


async def fetch_entries(
    start_date: str, end_date: str
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Fetch time entries for an inclusive local date range.

    Returns (entries, None) on success or ([], error_dict) on failure, so callers
    can tell an empty range apart from a failed request.
    """
    start_iso, end_iso = utc_range(start_date, end_date)
    result = await make_early_request("GET", f"/time-entries/{start_iso}/{end_iso}")
    if "error" in result:
        return [], result
    return result.get("timeEntries", []), None


def parse_iso(ts: str) -> datetime:
    """Parse an EARLY ISO timestamp."""
    return datetime.fromisoformat(ts)


def entry_hours(entry: dict[str, Any]) -> float:
    """Calculate hours for a single time entry."""
    d = entry.get("duration", {})
    start = parse_iso(d["startedAt"])
    stop = parse_iso(d["stoppedAt"])
    return (stop - start).total_seconds() / 3600
