import pytest

import early
import early_client
from early_client import overlapping_entries


def _entry(entry_id, started, stopped):
    return {
        "id": entry_id,
        "duration": {"startedAt": started, "stoppedAt": stopped},
    }


def test_overlapping_entries_ignores_a_shared_endpoint():
    # [14:00, 15:30). Ending at 14:00 or starting at 15:30 does not overlap.
    touching_before = _entry("1", "2026-02-16T13:00:00.000", "2026-02-16T14:00:00.000")
    inside = _entry("2", "2026-02-16T14:30:00.000", "2026-02-16T14:45:00.000")
    touching_after = _entry("3", "2026-02-16T15:30:00.000", "2026-02-16T16:00:00.000")
    found = overlapping_entries(
        [touching_before, inside, touching_after],
        "2026-02-16T14:00:00.000",
        "2026-02-16T15:30:00.000",
    )
    assert found == [inside]


def test_overlapping_entries_keeps_an_entry_it_cannot_time():
    broken = {"id": "1"}
    found = overlapping_entries([broken], "2026-02-16T14:00:00.000", "2026-02-16T15:00:00.000")
    assert found == [broken]


@pytest.fixture
def api(monkeypatch):
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


SPAN = ("2026-02-16T14:00:00Z", "2026-02-16T15:30:00Z")
CONFLICT = _entry("6", "2026-02-16T14:15:00.000", "2026-02-16T14:45:00.000")


@pytest.mark.anyio
async def test_create_time_entry_refuses_an_overlap_and_does_not_write(api):
    api.responses = [{"timeEntries": [CONFLICT]}, {"id": "should-not-post"}]
    result = await early.create_time_entry("7", *SPAN)
    assert result["conflicts"] == [CONFLICT]
    assert "overwrite=true" in result["error"]
    assert [c[0] for c in api.calls] == ["GET"]


@pytest.mark.anyio
async def test_create_time_entry_overwrite_skips_the_check(api):
    api.responses = [{"id": "9"}]
    await early.create_time_entry("7", *SPAN, overwrite=True)
    assert api.calls[0][:2] == ("POST", "/time-entries")


@pytest.mark.anyio
async def test_create_time_entry_allows_a_shared_endpoint(api):
    touching = _entry("5", "2026-02-16T13:00:00.000", "2026-02-16T14:00:00.000")
    api.responses = [{"timeEntries": [touching]}, {"id": "9"}]
    result = await early.create_time_entry("7", *SPAN)
    assert "error" not in result
    assert [c[0] for c in api.calls] == ["GET", "POST"]


@pytest.mark.anyio
async def test_create_time_entry_does_not_write_when_the_lookup_fails(api):
    api.responses = [{"error": "HTTP 503", "detail": "upstream"}]
    result = await early.create_time_entry("7", *SPAN)
    assert result["error"] == "HTTP 503"
    assert [c[0] for c in api.calls] == ["GET"]


RUNNING = {"startedAt": "2026-10-20T13:07:00.000", "activity": {"id": "3"}}


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr(early, "now_iso", lambda: "2026-10-20T14:52:40.000")


@pytest.mark.anyio
async def test_stop_tracking_refuses_an_overlap_and_leaves_the_timer_running(api, clock):
    # Inside the timer's 13:07-14:52 span. The February CONFLICT fixture is a different day.
    conflict = _entry("6", "2026-10-20T14:00:00.000", "2026-10-20T14:30:00.000")
    api.responses = [RUNNING, {"timeEntries": [conflict]}, {"id": "should-not-post"}]
    result = await early.stop_tracking()
    assert result["conflicts"] == [conflict]
    assert result["tracking"] == RUNNING
    assert "overwrite=true" in result["error"]
    assert [c[0] for c in api.calls] == ["GET", "GET"]
    assert api.calls[1][1] == "/time-entries/2026-10-20T13:07:00.000/2026-10-20T14:52:40.000"


@pytest.mark.anyio
async def test_stop_tracking_overwrite_stops_without_a_pre_check(api, clock):
    api.responses = [RUNNING, {"id": "7"}]
    await early.stop_tracking(overwrite=True)
    assert [c[:2] for c in api.calls] == [("GET", "/tracking"), ("POST", "/tracking/stop")]


@pytest.mark.anyio
async def test_stop_tracking_does_not_stop_when_the_lookup_fails(api, clock):
    api.responses = [RUNNING, {"error": "HTTP 503"}]
    result = await early.stop_tracking()
    assert result["error"] == "HTTP 503"
    assert result["tracking"] == RUNNING
    assert [c[0] for c in api.calls] == ["GET", "GET"]
