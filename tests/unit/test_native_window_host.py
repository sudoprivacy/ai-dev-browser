"""Native reveal keeps the authenticated owner, target and foreground boundaries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp
from aiohttp import web
import pytest

from ai_dev_browser.remote.control import ControlError
from ai_dev_browser.remote.native_window import (
    NativeWindowError,
    extension_process_id,
    run,
)
from ai_dev_browser.remote.existing import ExistingExtension
from ai_dev_browser.remote.worker import Worker, application


@pytest.mark.parametrize(
    "origin",
    [
        "https://127.0.0.1:9000",
        "http://example.com:9000",
        "http://0.0.0.0:9000",
        "http://fixture@127.0.0.1:9000",
        "http://127.0.0.1:9000/other",
        "http://127.0.0.1:9000?other=1",
        "http://127.0.0.1:9000#other",
    ],
)
def test_helper_rejects_unowned_endpoints_before_authentication(origin, monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Credentials must not be sent to an unowned endpoint")

    monkeypatch.setattr("urllib.request.build_opener", forbidden)
    with pytest.raises(NativeWindowError, match="native_window_endpoint_invalid"):
        run(
            {
                "origin": origin,
                "token": "private-host",
                "binding": {},
                "controller": "user-owner",
                "action": {"kind": "prepare-native-window"},
                "parentPid": 1,
            }
        )


async def test_native_descriptor_requires_current_human_owner_and_target(
    tmp_path, monkeypatch
):
    worker = Worker(tmp_path, "host", "agent", display_mode="native")
    worker.bind({"orgId": "fixture", "userId": "owner", "sessionId": "native-window"})
    page = SimpleNamespace(call=AsyncMock(), js=AsyncMock(return_value="Owned review"))
    session = SimpleNamespace(
        target_id="owned-tab", _connect_page=AsyncMock(return_value=page)
    )
    worker.session = session
    worker.browser = {"headless": False, "pid": 101}
    identity_calls = []

    def identity(pid):
        identity_calls.append(pid)
        return {"pid": pid, "created": 17, "executable": "owned/chrome.exe"}

    monkeypatch.setattr("ai_dev_browser.remote.worker.sys.platform", "win32")
    monkeypatch.setattr("ai_dev_browser.remote.worker.process_identity", identity)
    worker.state = AsyncMock(return_value={"activeTargetId": "owned-tab"})
    action = {
        "kind": "prepare-native-window",
        "targetId": "owned-tab",
        "controlEpoch": 0,
        "targetEpoch": 0,
    }
    try:
        with pytest.raises(ControlError, match="browser_control_not_owned"):
            await worker.prepare_native_window("user-owner", action)
        assert not identity_calls
        await worker.control.take("user-owner")
        action["controlEpoch"] = worker.control.epoch
        with pytest.raises(ControlError, match="browser_control_not_owned"):
            await worker.prepare_native_window("user-other", action)
        with pytest.raises(ControlError, match="stale_browser_operation"):
            await worker.prepare_native_window(
                "user-owner", {**action, "targetId": "different-tab"}
            )
        assert not identity_calls
        reply = await worker.prepare_native_window("user-owner", action)
        assert reply["nativeWindow"]["process"]["pid"] == 101
        assert reply["nativeWindow"]["title"] == "Owned review"
        page.call.assert_awaited_once_with("Page.bringToFront")
        worker.control.target_epoch += 1
        with pytest.raises(ControlError, match="stale_browser_operation"):
            await worker.prepare_native_window("user-owner", action)
        assert identity_calls == [101]
    finally:
        worker.session = None
        worker.browser = None
        await worker.close()


async def test_native_descriptor_rejects_cloud_display_before_browser_access(
    tmp_path, monkeypatch
):
    worker = Worker(tmp_path, "host", "agent", display_mode="x11")
    monkeypatch.setattr("ai_dev_browser.remote.worker.sys.platform", "win32")
    try:
        with pytest.raises(ControlError, match="native_window_not_supported"):
            await worker.prepare_native_window(
                "user-owner",
                {
                    "kind": "prepare-native-window",
                    "targetId": "tab",
                    "controlEpoch": 0,
                    "targetEpoch": 0,
                },
            )
    finally:
        await worker.close()


async def test_native_helper_metadata_and_descriptor_are_host_only(tmp_path):
    worker = Worker(tmp_path, "private-host", "private-agent", display_mode="native")
    runner = web.AppRunner(application(worker))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    origin = "http://127.0.0.1:" + str(site._server.sockets[0].getsockname()[1])
    try:
        async with aiohttp.ClientSession() as http:
            async with http.get(
                origin + "/binding", headers={"Authorization": "Bearer private-agent"}
            ) as response:
                assert response.status == 403
            async with http.post(
                origin + "/invoke",
                headers={"Authorization": "Bearer private-agent"},
                json={
                    "controller": "user-owner",
                    "binding": {},
                    "action": {"kind": "prepare-native-window"},
                },
            ) as response:
                assert response.status == 403
            assert worker.binding is None
    finally:
        await runner.cleanup()


def test_personal_chrome_process_follows_only_the_selected_local_bridge(monkeypatch):
    import psutil

    parent = SimpleNamespace(
        pid=12, exe=lambda: "/owned/chrome.exe", cmdline=lambda: ["chrome.exe"]
    )
    processes = {
        11: SimpleNamespace(
            exe=lambda: "/owned/chrome.exe",
            cmdline=lambda: ["chrome.exe", "--type=utility"],
            parent=lambda: parent,
        ),
        99: SimpleNamespace(exe=lambda: "/other/python.exe"),
    }

    def connection(pid, port):
        return SimpleNamespace(
            status=psutil.CONN_ESTABLISHED,
            pid=pid,
            raddr=SimpleNamespace(ip="127.0.0.1", port=port),
            laddr=SimpleNamespace(ip="127.0.0.1"),
        )

    monkeypatch.setattr("ai_dev_browser.remote.native_window.sys.platform", "win32")
    monkeypatch.setattr(
        psutil,
        "net_connections",
        lambda **_kwargs: [
            connection(11, 9361),
            connection(99, 9361),
            connection(1234, 9999),
        ],
    )
    monkeypatch.setattr(psutil, "Process", lambda pid: processes[pid])
    assert extension_process_id(9361) == 12
    other = SimpleNamespace(
        pid=13, exe=lambda: "/other/chrome.exe", cmdline=lambda: ["chrome.exe"]
    )
    processes[99] = other
    with pytest.raises(NativeWindowError, match="native_window_process_ambiguous"):
        extension_process_id(9361)


def test_personal_process_permission_failure_is_preserved_without_fallback(monkeypatch):
    import psutil

    calls = []

    def denied(**_kwargs):
        calls.append(True)
        raise psutil.AccessDenied()

    monkeypatch.setattr("ai_dev_browser.remote.native_window.sys.platform", "win32")
    monkeypatch.setattr(psutil, "net_connections", denied)
    with pytest.raises(
        NativeWindowError, match="native_window_process_unavailable"
    ) as caught:
        extension_process_id(9361)
    assert caught.value.details == {"reason": "AccessDenied"}
    assert calls == [True]


async def test_personal_bridge_identity_is_rechecked_after_process_lookup(
    tmp_path, monkeypatch
):
    original = {
        "extension_connected": True,
        "session_id": "run",
        "profile_id": "chosen",
    }
    changed = {**original, "profile_id": "other"}
    status = AsyncMock(side_effect=[original, changed])
    monkeypatch.setattr("ai_dev_browser.remote.existing.bridge_status", status)
    monkeypatch.setattr(
        "ai_dev_browser.remote.native_window.extension_process_id", lambda _port: 17
    )
    extension = ExistingExtension(tmp_path)
    with pytest.raises(ControlError, match="browser_existing_extension_changed"):
        await extension.native_process_id(
            {"sessionId": "extension-run", "profileId": "chosen"}
        )
    assert status.await_count == 2
