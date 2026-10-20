import pytest

import early
import early_cli


@pytest.fixture
def tools(monkeypatch):
    """Replace the tools the CLI calls; record which timer gets stopped."""
    calls = []

    def install(tracking):
        async def current_tracking():
            return tracking

        async def stop_running(running, round_minutes):
            calls.append((running, round_minutes))
            return {"id": "7"}

        monkeypatch.setattr(early, "current_tracking", current_tracking)
        monkeypatch.setattr(early, "stop_running", stop_running)
        return calls

    return install


@pytest.mark.anyio
async def test_stop_leaves_timer_in_another_folder_running(tools):
    calls = tools({"activity": {"folderId": "45230"}, "startedAt": "2026-10-20T13:00:00.000"})
    result = await early_cli.stop(15, "353867")
    assert result["stopped"] is False
    assert calls == []


@pytest.mark.anyio
async def test_stop_rounds_the_timer_it_checked(tools):
    running = {"activity": {"folderId": 353867}, "startedAt": "2026-10-20T13:00:00.000"}
    calls = tools(running)  # an int folder id from EARLY still matches
    await early_cli.stop(15, "353867")
    assert calls == [(running, 15)]


@pytest.mark.anyio
async def test_stop_with_nothing_running_is_not_an_error(tools):
    calls = tools({"error": "HTTP 404", "detail": '{"error":{"message":"Current tracking does not exist"}}'})
    result = await early_cli.stop(15, "353867")
    assert result == {"stopped": False, "reason": "nothing tracking"}
    assert calls == []


@pytest.mark.anyio
async def test_stop_passes_auth_failures_through(tools):
    tools({"error": "Authentication failed: HTTP 401"})
    result = await early_cli.stop(15, "353867")
    assert "error" in result
