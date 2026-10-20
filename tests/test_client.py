from datetime import date

import pytest

import early_client
from early_client import date_range_for_period, to_api_ts, utc_range, utc_to_local


def test_utc_range_shifts_local_day_to_utc_bounds(new_york):
    # Matches what the EARLY desktop app sends for a New York week (EST, UTC-5).
    assert utc_range("2025-12-07", "2025-12-13") == (
        "2025-12-07T05:00:00.000",
        "2025-12-14T04:59:59.999",
    )


def test_utc_range_uses_dst_offset_per_day(new_york):
    # 2026-03-08 is the spring-forward day: starts at EST, ends at EDT.
    assert utc_range("2026-03-08", "2026-03-08") == (
        "2026-03-08T05:00:00.000",
        "2026-03-09T03:59:59.999",
    )


def test_to_api_ts_treats_naive_input_as_local(new_york):
    assert to_api_ts("2026-02-16T09:00:00") == "2026-02-16T14:00:00.000"


def test_to_api_ts_converts_offset_input(new_york):
    assert to_api_ts("2026-02-16T09:00:00+01:00") == "2026-02-16T08:00:00.000"
    assert to_api_ts("2026-02-16T09:00:00Z") == "2026-02-16T09:00:00.000"


def test_to_api_ts_rejects_garbage(new_york):
    with pytest.raises(ValueError):
        to_api_ts("next tuesday")


def test_utc_to_local_returns_local_wall_clock(new_york):
    assert utc_to_local("2025-12-16T16:00:58.596").strftime("%Y-%m-%d %H:%M") == "2025-12-16 11:00"


def test_date_range_for_period_last_month():
    assert date_range_for_period("last_month", today=date(2026, 3, 15)) == ("2026-02-01", "2026-02-28")


def test_date_range_for_period_rejects_unknown():
    with pytest.raises(ValueError):
        date_range_for_period("fortnight", today=date(2026, 3, 15))


@pytest.mark.anyio
async def test_fetch_entries_returns_error_instead_of_empty_list(monkeypatch, new_york):
    async def failing_request(method, path, **kwargs):
        return {"error": "HTTP 500", "path": path}

    monkeypatch.setattr(early_client, "make_early_request", failing_request)
    entries, error = await early_client.fetch_entries("2026-02-01", "2026-02-01")
    assert entries == []
    assert error == {"error": "HTTP 500", "path": "/time-entries/2026-02-01T05:00:00.000/2026-02-02T04:59:59.999"}


@pytest.mark.anyio
async def test_fetch_entries_queries_utc_bounds(monkeypatch, new_york):
    seen = {}

    async def ok_request(method, path, **kwargs):
        seen["path"] = path
        return {"timeEntries": []}

    monkeypatch.setattr(early_client, "make_early_request", ok_request)
    assert await early_client.fetch_entries("2026-07-01", "2026-07-01") == ([], None)
    assert seen["path"] == "/time-entries/2026-07-01T04:00:00.000/2026-07-02T03:59:59.999"
