"""Private Worker recording configuration cannot come from request fields."""

import pytest

from ai_dev_browser.remote.worker import Worker
from test_worker_host_authorization import CurrentAccess, request, serving, with_page


@pytest.mark.parametrize(
    "factory,extra,code",
    [
        (False, {}, "browser_authorization_required"),
        (True, {}, "browser_recording_store_required"),
        (True, {"recording_sink": True}, "invalid_browser_request"),
        (True, {"event_sink": "client-supplied"}, "invalid_browser_request"),
        (True, {"recording_event_sink": "client-supplied"}, "invalid_browser_request"),
    ],
)
async def test_record_start_requires_actual_server_authority_and_writer(
    tmp_path, factory, extra, code
):
    worker = Worker(
        tmp_path, "host-fixture", "agent-fixture", require_host_authorization=factory
    )
    effects = await with_page(worker)
    options = {"host_authorization": CurrentAccess()} if factory else {}
    async with serving(worker, **options) as (http, origin):
        action = {
            "kind": "record-start",
            "recordingId": "original",
            "controlEpoch": 1,
            "targetEpoch": 0,
            **extra,
        }
        async with http.post(origin + "/invoke", json=request(action)) as response:
            assert response.status in (400, 409)
            assert await response.json() == {"error": code}
        assert worker.session._recording is None and effects == []
