import pytest

import early
import early_cli


@pytest.fixture
def tools(monkeypatch):
    """Replace the tools the CLI calls; record stop calls."""
    calls = []

    def install(tracking):
        async def current_tracking():
            return tracking

        async def stop_tracking(round_minutes=0):
            calls.append(round_minutes)
            return {"id": "7"}

        monkeypatch.setattr(early, "current_tracking", current_tracking)
        monkeypatch.setattr(early, "stop_tracking", stop_tracking)
        return calls

    return install


@pytest.mark.anyio
async def test_stop_leaves_timer_in_another_folder_running(tools):
    calls = tools({"activity": {"folderId": "45230"}, "startedAt": "2026-10-20T13:00:00.000"})
    result = await early_cli.stop(15, "353867")
    assert result["stopped"] is False
    assert calls == []


@pytest.mark.anyio
async def test_stop_rounds_timer_in_matching_folder(tools):
    calls = tools({"activity": {"folderId": "353867"}, "startedAt": "2026-10-20T13:00:00.000"})
    await early_cli.stop(15, "353867")
    assert calls == [15]


@pytest.mark.anyio
async def test_stop_with_nothing_running_is_not_an_error(tools):
    calls = tools({"error": "HTTP 404"})
    result = await early_cli.stop(15, "353867")
    assert result == {"stopped": False, "reason": "nothing tracking"}
    assert calls == []
