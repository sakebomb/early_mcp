from datetime import datetime

import pytest

import early
import early_client
from early_client import clamp_span, local_day_hours, round_to_minutes, rounded_span


def _entry(name, started, stopped, note="", folder="1"):
    return {
        "id": "7",
        "activity": {"name": name, "folderId": folder},
        "duration": {"startedAt": started, "stoppedAt": stopped},
        "note": {"text": note, "tags": [], "mentions": []},
    }


@pytest.fixture
def api(monkeypatch):
    """Answer each call from a queue of responses and record what was sent."""

    class Stub:
        responses: list = []
        calls: list = []

    stub = Stub()
    stub.responses, stub.calls = [], []

    async def fake_request(method, path, json_body=None, params=None):
        stub.calls.append((method, path, json_body))
        return stub.responses.pop(0)

    monkeypatch.setattr(early_client, "make_early_request", fake_request)
    monkeypatch.setattr(early, "make_early_request", fake_request)
    return stub


@pytest.mark.parametrize(
    "ts, expected",
    [("10:07:29", "10:00"), ("10:07:30", "10:15"), ("10:52:31", "11:00"), ("10:15:00", "10:15")],
)
def test_round_to_minutes_snaps_to_nearest_quarter(ts, expected):
    dt = datetime.fromisoformat(f"2026-10-20T{ts}")
    assert round_to_minutes(dt, 15).strftime("%H:%M") == expected


def test_rounded_span_never_rounds_to_zero():
    start, stop = rounded_span(datetime(2026, 10, 20, 10, 1), datetime(2026, 10, 20, 10, 5), 15)
    assert (start.strftime("%H:%M"), stop.strftime("%H:%M")) == ("10:00", "10:15")


def test_local_day_hours_splits_at_local_midnight(new_york):
    # 22:00 to 01:30 New York (EDT, UTC-4).
    entry = _entry("Developing", "2026-10-20T02:00:00.000", "2026-10-20T05:30:00.000")
    days = {d.isoformat(): h for d, h in local_day_hours(entry).items()}
    assert days == {"2026-10-19": 2.0, "2026-10-20": 1.5}


def test_local_day_hours_uses_each_days_dst_offset(new_york):
    # DST ends 2026-11-01 at 02:00 EDT; 23:00 Oct 31 to 03:00 EST Nov 1 is 5 real hours.
    entry = _entry("Developing", "2026-11-01T03:00:00.000", "2026-11-01T08:00:00.000")
    days = {d.isoformat(): h for d, h in local_day_hours(entry).items()}
    assert days == {"2026-10-31": 1.0, "2026-11-01": 4.0}


RUNNING = {"startedAt": "2026-10-20T13:07:00.000"}
STOPPED = _entry("Developing", "2026-10-20T13:07:00.000", "2026-10-20T14:52:40.000")


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr(early, "now_iso", lambda: "2026-10-20T14:52:40.000")


@pytest.mark.anyio
async def test_stop_tracking_rounds_entry_to_quarter_hours(api, clock):
    api.responses = [RUNNING, STOPPED, {"timeEntries": [STOPPED]}, {"id": "7"}]
    await early.stop_tracking(round_minutes=15)
    assert api.calls[3] == (
        "PATCH",
        "/time-entries/7",
        {"startedAt": "2026-10-20T13:00:00.000", "stoppedAt": "2026-10-20T15:00:00.000"},
    )


@pytest.mark.anyio
async def test_stop_tracking_rounding_never_overlaps_an_off_grid_neighbour(api, clock):
    # The previous entry (made in the app) ends at 13:04; rounding the start to 13:00
    # would overlap it and EARLY would split it, so the start stays at 13:04.
    before = {**_entry("Meeting", "2026-10-20T12:30:00.000", "2026-10-20T13:04:00.000"), "id": "6"}
    api.responses = [RUNNING, STOPPED, {"timeEntries": [before, STOPPED]}, {"id": "7"}]
    await early.stop_tracking(round_minutes=15)
    assert api.calls[3][2] == {"startedAt": "2026-10-20T13:04:00.000", "stoppedAt": "2026-10-20T15:00:00.000"}


def test_clamp_span_keeps_exact_times_when_under_a_minute_remains():
    exact = (datetime(2026, 10, 20, 13, 7), datetime(2026, 10, 20, 13, 9))
    rounded = (datetime(2026, 10, 20, 13, 0), datetime(2026, 10, 20, 13, 15))
    others = [(datetime(2026, 10, 20, 12, 0), datetime(2026, 10, 20, 13, 7)),
              (datetime(2026, 10, 20, 13, 9), datetime(2026, 10, 20, 14, 0))]
    assert clamp_span(*rounded, exact, others) == (datetime(2026, 10, 20, 13, 7), datetime(2026, 10, 20, 13, 9))


@pytest.mark.anyio
async def test_stop_tracking_without_rounding_does_not_patch(api, clock):
    api.responses = [RUNNING, STOPPED]
    await early.stop_tracking()
    assert [c[0] for c in api.calls] == ["GET", "POST"]


@pytest.mark.anyio
async def test_stop_tracking_leaves_timer_under_a_minute_running(api, clock):
    # EARLY would answer 400 and discard the timer, so the stop is never sent.
    api.responses = [{"startedAt": "2026-10-20T14:52:10.000"}]
    result = await early.stop_tracking(round_minutes=15)
    assert "under 1 minute" in result["error"]
    assert [c[0] for c in api.calls] == ["GET"]


@pytest.mark.anyio
async def test_stop_tracking_reports_failed_rounding_with_stopped_entry(api, clock):
    stopped = STOPPED
    api.responses = [RUNNING, stopped, {"timeEntries": [stopped]}, {"error": "HTTP 400"}]
    result = await early.stop_tracking(round_minutes=15)
    assert result["error"] == "HTTP 400"
    assert result["stopped_entry"] == stopped


@pytest.mark.anyio
async def test_stop_tracking_rejects_step_that_does_not_divide_an_hour(api):
    assert "error" in await early.stop_tracking(round_minutes=7)
    assert api.calls == []


@pytest.mark.anyio
async def test_timesheet_sums_rows_per_day_then_rounds(api, new_york):
    api.responses = [{"timeEntries": [
        # Two 10-minute entries on the same row: 20 minutes rounds to 0.25, not 0 + 0.
        _entry("Developing", "2026-10-20T13:00:00.000", "2026-10-20T13:10:00.000", "roadmap#355"),
        _entry("Developing", "2026-10-20T15:00:00.000", "2026-10-20T15:10:00.000", "roadmap#355"),
        _entry("Code Review", "2026-10-20T16:00:00.000", "2026-10-20T17:00:00.000", "malpack#160"),
        _entry("Halioc", "2026-10-20T18:00:00.000", "2026-10-20T19:00:00.000", "", folder="2"),
    ]}]
    result = await early.timesheet("2026-10-17", "2026-10-30", folder_id="1")
    assert result["rows"] == [
        {"row": "Code Review: malpack#160", "days": {"2026-10-20": 1.0}, "total": 1.0},
        {"row": "Developing: roadmap#355", "days": {"2026-10-20": 0.25}, "total": 0.25},
    ]
    assert result["total_hours"] == 1.25


@pytest.mark.anyio
async def test_timesheet_skips_rows_that_round_to_nothing(api, new_york):
    api.responses = [{"timeEntries": [
        _entry("Developing", "2026-10-20T13:00:00.000", "2026-10-20T13:05:00.000", "roadmap#355"),
    ]}]
    result = await early.timesheet("2026-10-17", "2026-10-30", folder_id="1")
    assert result["rows"] == []


@pytest.mark.anyio
async def test_timesheet_drops_hours_outside_the_period(api, new_york):
    # Starts 23:00 on the last day; the part after midnight belongs to the next period.
    api.responses = [{"timeEntries": [
        _entry("Developing", "2026-10-31T03:00:00.000", "2026-10-31T05:00:00.000", "roadmap#401"),
    ]}]
    result = await early.timesheet("2026-10-17", "2026-10-30", folder_id="1")
    assert result["rows"][0]["days"] == {"2026-10-30": 1.0}
