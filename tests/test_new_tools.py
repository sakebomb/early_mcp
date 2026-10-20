import pytest

import early
import early_client


@pytest.fixture
def api(monkeypatch):
    """Record API calls instead of sending them."""
    calls = []

    async def fake_request(method, path, json_body=None, params=None):
        calls.append((method, path, json_body))
        return {}

    monkeypatch.setattr(early_client, "make_early_request", fake_request)
    monkeypatch.setattr(early, "make_early_request", fake_request)
    return calls


@pytest.mark.anyio
@pytest.mark.parametrize(
    "call, expected",
    [
        (lambda: early.get_me(), ("GET", "/me", None)),
        (lambda: early.list_tags_and_mentions(), ("GET", "/tags-and-mentions", None)),
        (lambda: early.get_time_entry("9"), ("GET", "/time-entries/9", None)),
        (lambda: early.cancel_tracking(), ("DELETE", "/tracking", None)),
        (lambda: early.unarchive_activity("4"), ("POST", "/activities/4/unarchive", None)),
    ],
    ids=["get_me", "tags", "get_time_entry", "cancel_tracking", "unarchive"],
)
async def test_simple_tools_hit_documented_endpoints(api, call, expected):
    await call()
    assert api == [expected]


@pytest.mark.anyio
async def test_edit_time_entry_sends_only_given_fields_in_utc(api, new_york):
    await early.edit_time_entry("9", stopped_at="2026-02-16T10:30:00")
    assert api == [("PATCH", "/time-entries/9", {"stoppedAt": "2026-02-16T15:30:00.000"})]


@pytest.mark.anyio
async def test_edit_time_entry_empty_note_removes_note(api):
    # EARLY ignores {"note": null}; only an empty text clears it.
    await early.edit_time_entry("9", note="")
    assert api == [("PATCH", "/time-entries/9", {"note": {"text": ""}})]


@pytest.mark.anyio
async def test_edit_time_entry_without_fields_is_rejected(api):
    result = await early.edit_time_entry("9")
    assert "error" in result
    assert api == []


@pytest.mark.anyio
async def test_edit_time_entry_bad_timestamp_is_rejected(api):
    result = await early.edit_time_entry("9", started_at="noon")
    assert "Invalid timestamp" in result["error"]
    assert api == []


@pytest.mark.anyio
async def test_edit_tracking_switches_activity_and_note(api):
    await early.edit_tracking(activity_id="3", note="standup")
    assert api == [("PATCH", "/tracking", {"activityId": "3", "note": {"text": "standup"}})]


@pytest.mark.anyio
async def test_create_activity_sends_required_folder_id(api):
    # EARLY answers 400 "FolderId is empty" without it.
    await early.create_activity("Deep Work", folder_id="45230")
    assert api == [("POST", "/activities", {"name": "Deep Work", "color": "#4CAF50", "folderId": "45230"})]


@pytest.mark.anyio
async def test_edit_tracking_empty_note_removes_note(api):
    await early.edit_tracking(note="")
    assert api == [("PATCH", "/tracking", {"note": {"text": ""}})]


@pytest.mark.anyio
async def test_ids_are_escaped_as_one_path_segment(api):
    await early.delete_time_entry("1/../../activities/2")
    assert api == [("DELETE", "/time-entries/1%2F..%2F..%2Factivities%2F2", None)]


@pytest.mark.anyio
async def test_edit_tracking_converts_start_to_utc(api, new_york):
    await early.edit_tracking(started_at="2026-07-01T09:00:00")
    assert api == [("PATCH", "/tracking", {"startedAt": "2026-07-01T13:00:00.000"})]


@pytest.mark.anyio
async def test_edit_tracking_without_fields_is_rejected(api):
    assert "error" in await early.edit_tracking()
    assert api == []


@pytest.mark.anyio
async def test_every_tool_declares_annotations():
    tools = await early.mcp.list_tools()
    missing = [t.name for t in tools if t.annotations is None]
    assert missing == []


@pytest.mark.anyio
async def test_tools_that_can_lose_tracked_time_are_marked_destructive():
    hints = {t.name: t.annotations for t in await early.mcp.list_tools()}
    for name in ("create_time_entry", "edit_time_entry", "delete_time_entry", "stop_tracking", "cancel_tracking"):
        assert hints[name].destructiveHint is True, name
    assert hints["start_tracking"].destructiveHint is False
    for name in ("list_time_entries", "time_summary", "get_me"):
        assert hints[name].readOnlyHint is True, name


@pytest.mark.anyio
async def test_explore_api_hint_matches_write_setting_at_import():
    # The hint is fixed when early.py is imported, so compare against that setting.
    hint = {t.name: t.annotations for t in await early.mcp.list_tools()}["explore_api"]
    if early._explore_writes_enabled():
        assert hint.destructiveHint is True
    else:
        assert hint.readOnlyHint is True
