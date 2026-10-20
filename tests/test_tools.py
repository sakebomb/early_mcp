import pytest

import early
import early_client


def _entry(name, started, stopped):
    return {"activity": {"name": name}, "duration": {"startedAt": started, "stoppedAt": stopped}}


@pytest.fixture
def api(monkeypatch):
    """Stub the API layer; tests set .response and inspect .calls."""

    class Stub:
        response: dict = {"timeEntries": []}
        calls: list = []

    stub = Stub()
    stub.calls = []

    async def fake_request(method, path, json_body=None, params=None):
        stub.calls.append((method, path, json_body))
        return stub.response

    monkeypatch.setattr(early_client, "make_early_request", fake_request)
    monkeypatch.setattr(early, "make_early_request", fake_request)
    return stub


@pytest.mark.anyio
@pytest.mark.parametrize(
    "call",
    [
        lambda: early.time_summary("today"),
        lambda: early.efficiency_report("2026-02-01", "2026-02-02"),
        lambda: early.billing_report("2026-02-01", "2026-02-02", 100.0),
    ],
    ids=["time_summary", "efficiency_report", "billing_report"],
)
async def test_reports_surface_api_errors_not_zero_hours(api, new_york, call):
    api.response = {"error": "Authentication failed: bad key"}
    result = await call()
    assert result.get("error") == "Authentication failed: bad key"
    assert "total_hours" not in result


@pytest.mark.anyio
async def test_time_summary_empty_range_reports_zero(api, new_york):
    result = await early.time_summary("today")
    assert result["total_hours"] == 0
    assert "error" not in result


@pytest.mark.anyio
async def test_efficiency_report_buckets_by_local_day(api, new_york):
    # 02:00 UTC on the 3rd is 21:00 on the 2nd in New York.
    api.response = {"timeEntries": [_entry("Work", "2026-02-03T02:00:00.000", "2026-02-03T03:00:00.000")]}
    result = await early.efficiency_report("2026-02-02", "2026-02-02")
    assert result["daily_breakdown"] == [{"date": "2026-02-02", "hours": 1.0}]


@pytest.mark.anyio
async def test_list_time_entries_sends_utc_bounds(api, new_york):
    await early.list_time_entries("2026-02-01", "2026-02-01")
    assert api.calls[0][1] == "/time-entries/2026-02-01T05:00:00.000/2026-02-02T04:59:59.999"


@pytest.mark.anyio
async def test_create_time_entry_converts_local_times_to_utc(api, new_york):
    await early.create_time_entry("7", "2026-02-16T09:00:00", "2026-02-16T10:30:00")
    method, path, body = api.calls[0]
    assert (method, path) == ("POST", "/time-entries")
    assert body["startedAt"] == "2026-02-16T14:00:00.000"
    assert body["stoppedAt"] == "2026-02-16T15:30:00.000"


@pytest.mark.anyio
async def test_create_time_entry_rejects_bad_timestamp_without_calling_api(api, new_york):
    result = await early.create_time_entry("7", "yesterday morning", "2026-02-16T10:30:00")
    assert "error" in result
    assert api.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["DELETE", "post", "PATCH"])
async def test_explore_api_blocks_writes_by_default(api, monkeypatch, method):
    monkeypatch.delenv("EARLY_EXPLORE_ALLOW_WRITES", raising=False)
    result = await early.explore_api(method, "/time-entries/1")
    assert "disabled" in result["error"]
    assert api.calls == []


@pytest.mark.anyio
async def test_explore_api_allows_get(api):
    await early.explore_api("get", "/me")
    assert api.calls[0][:2] == ("GET", "/me")


@pytest.mark.anyio
async def test_explore_api_allows_writes_when_enabled(api, monkeypatch):
    monkeypatch.setenv("EARLY_EXPLORE_ALLOW_WRITES", "1")
    await early.explore_api("DELETE", "/time-entries/1")
    assert api.calls[0][:2] == ("DELETE", "/time-entries/1")
