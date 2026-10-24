"""Viewer context checks must never change browser ownership or claim a profile."""

import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_dev_browser.remote.control import ControlError
from ai_dev_browser.remote.worker import Worker
from ai_dev_browser.remote.window_stream import WindowStream


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"sessionId": "other-task"}, "browser_session_changed"),
        ({"userId": "other-owner"}, "browser_session_changed"),
        ({"orgId": "other-tenant"}, "browser_session_changed"),
        ({"controlEpoch": 7}, "stale_browser_operation"),
        ({"targetEpoch": 7}, "stale_browser_operation"),
        ({"viewerId": "unattached"}, "browser_viewer_not_attached"),
        ({"viewerId": ""}, "invalid_browser_viewer"),
    ],
)
def test_rejecting_stream_context_preserves_binding_and_lease(tmp_path, change, code):
    worker = Worker(tmp_path, "host", "agent", display_mode="native")
    binding = {"orgId": "tenant", "userId": "owner", "sessionId": "original-task"}
    worker.bind(binding)
    worker.session = SimpleNamespace()
    worker.window_viewers.add("user-owner:attached")
    worker.control.state = "human"
    worker.control.controller = "user-owner"
    before = copy.deepcopy(worker.control.snapshot())
    journal = worker.journal.read_bytes()
    context = {
        **binding,
        "controlEpoch": 0,
        "targetEpoch": 0,
        "viewerId": "attached",
        **change,
    }
    with pytest.raises(ControlError, match=code):
        worker.check_window_stream(
            {key: context[key] for key in binding}, "user-owner", context
        )
    assert worker.binding == binding
    assert worker.control.snapshot() == before
    assert worker.journal.read_bytes() == journal
    assert not worker.window_stream_connections and worker.display is None


async def test_headless_stream_allocates_no_display_or_viewer(tmp_path):
    worker = Worker(tmp_path, "host", "agent", display_mode="native")
    worker.bind({"orgId": "tenant", "userId": "owner", "sessionId": "task"})
    worker.browser = {"headless": True}
    with pytest.raises(ControlError, match="browser_window_view_unavailable"):
        await worker.open_window_stream()
    assert worker.window_stream._view is None
    assert worker.display is None


async def test_invalid_display_does_not_retain_protocol_credentials():
    stream = WindowStream("")
    with pytest.raises(ValueError, match="isolated display"):
        await stream.start()
    assert stream.view is None and not stream.connections
    assert not Path(stream.directory.name).exists()
