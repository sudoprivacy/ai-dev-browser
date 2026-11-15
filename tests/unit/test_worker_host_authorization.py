"""Actual private Worker HTTP paths consume one server-supplied host assertion.

The page transport and grants are explicit fixtures; these are not production
provider or Chrome/native acceptance cases.
"""

import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from urllib.parse import quote

import aiohttp
from aiohttp import web
import pytest

from ai_dev_browser.remote.control import ControlError
from ai_dev_browser.remote.session import BrowserSession
from ai_dev_browser.remote.worker import Worker, application

BINDING = {
    "orgId": "original-org",
    "userId": "original-user",
    "sessionId": "original-run",
}
CONTROLLER = "user-original"


class CurrentAccess:
    def __init__(self):
        self.allowed = True
        self.created = asyncio.Event()
        self.observed = []
        self.assertions = 0

    async def __call__(self, request, binding, controller, action):
        self.observed.append((binding, controller, action))
        self.created.set()
        return self.check

    async def check(self):
        self.assertions += 1
        if not self.allowed:
            raise PermissionError("private original grant")


@asynccontextmanager
async def serving(worker, **options):
    runner = web.AppRunner(application(worker, **options))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        async with aiohttp.ClientSession(
            headers={"Authorization": "Bearer host-fixture"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as http:
            yield http, f"http://127.0.0.1:{port}"
    finally:
        await runner.cleanup()


def request(action):
    return {"binding": BINDING.copy(), "controller": CONTROLLER, "action": action}


def worker_at(tmp_path):
    return Worker(
        tmp_path, "host-fixture", "agent-fixture", require_host_authorization=True
    )


async def with_page(worker):
    effects = []

    class Browser:
        _automation_target_id = "page"
        tabs = [
            SimpleNamespace(
                _target=SimpleNamespace(
                    target_id="page", title="fixture", url="https://fixture.example/"
                )
            )
        ]

        async def update_targets(self):
            pass

        async def close(self):
            pass

    class Page:
        disconnected = False

        async def call(self, method, params=None):
            assert method == "Page.reload"
            effects.append(method)

        async def close(self):
            self.disconnected = True

    worker.bind(BINDING.copy())
    await worker.control.take(CONTROLLER)
    worker.browser = {
        "session_id": "fixture",
        "transport": "cdp",
        "headless": True,
        "external_attachment": True,
    }
    worker.session = BrowserSession(Browser(), None, control=worker.control)
    worker.session._page = Page()
    return effects


async def test_managed_host_token_alone_cannot_claim_binding(tmp_path):
    worker = worker_at(tmp_path)
    async with serving(worker) as (http, origin):
        async with http.post(
            origin + "/invoke", json=request({"kind": "state"})
        ) as response:
            assert response.status == 409
            assert await response.json() == {"error": "browser_authorization_required"}
    assert worker.binding is None
    assert not worker.journal.exists()


@pytest.mark.parametrize("completion", [None, True, False, {}])
async def test_malformed_factory_cannot_write_first_binding(tmp_path, completion):
    worker = worker_at(tmp_path)

    async def factory(*args):
        return completion

    async with serving(worker, host_authorization=factory) as (http, origin):
        async with http.post(
            origin + "/invoke", json=request({"kind": "state"})
        ) as response:
            assert response.status == 409
            assert await response.json() == {"error": "invalid_browser_authorization"}
    assert worker.binding is None
    assert not worker.journal.exists()


async def test_queued_human_input_rechecks_original_current_access(tmp_path):
    worker, access = worker_at(tmp_path), CurrentAccess()
    effects = await with_page(worker)
    await worker.control._operations.acquire()
    async with serving(worker, host_authorization=access) as (http, origin):
        task = asyncio.create_task(
            http.post(
                origin + "/invoke",
                json=request(
                    {
                        "kind": "reload",
                        "controlEpoch": 1,
                        "targetEpoch": 0,
                    }
                ),
            )
        )
        await access.created.wait()
        assert worker.control._operations._waiters
        access.allowed = False
        worker.control._operations.release()
        async with await task as response:
            assert response.status == 409
            assert await response.json() == {"error": "browser_authorization_denied"}
    assert effects == []
    assert worker.binding == BINDING
    assert worker.control.state == "human"
    assert access.observed == [
        (
            BINDING,
            CONTROLLER,
            {
                "kind": "reload",
                "controlEpoch": 1,
                "targetEpoch": 0,
            },
        )
    ]


async def test_factory_cannot_mutate_original_binding_or_dispatch_action(tmp_path):
    worker = worker_at(tmp_path)
    effects = await with_page(worker)

    async def factory(request, binding, controller, action):
        binding["orgId"] = "foreign"
        action["kind"] = "stop"

        async def check():
            return None

        return check

    async with serving(worker, host_authorization=factory) as (http, origin):
        async with http.post(
            origin + "/invoke",
            json=request(
                {
                    "kind": "reload",
                    "controlEpoch": 1,
                    "targetEpoch": 0,
                }
            ),
        ) as response:
            assert response.status == 200
            assert (await response.json())["session"]["state"] == "human"
    assert effects == ["Page.reload"]
    assert worker.binding == BINDING


async def test_post_input_withdrawal_withholds_reply_without_replay(tmp_path):
    worker, access = worker_at(tmp_path), CurrentAccess()
    effects = await with_page(worker)
    page = worker.session._page
    original = page.call

    async def sent(method, params=None):
        result = await original(method, params)
        access.allowed = False
        return result

    page.call = sent
    async with serving(worker, host_authorization=access) as (http, origin):
        async with http.post(
            origin + "/invoke",
            json=request(
                {
                    "kind": "reload",
                    "controlEpoch": 1,
                    "targetEpoch": 0,
                }
            ),
        ) as response:
            assert response.status == 409
            assert await response.json() == {"error": "browser_authorization_denied"}
    assert effects == ["Page.reload"]


async def test_binding_changed_while_assertion_awaits_cannot_claim_profile(tmp_path):
    worker = worker_at(tmp_path)

    async def factory(*args):
        async def check():
            worker.binding = {**BINDING, "sessionId": "different-run"}

        return check

    async with serving(worker, host_authorization=factory) as (http, origin):
        async with http.post(
            origin + "/invoke", json=request({"kind": "state"})
        ) as response:
            assert response.status == 409
            assert await response.json() == {"error": "browser_authorization_denied"}
    assert worker.binding["sessionId"] == "different-run"
    assert not worker.journal.exists()


async def test_held_upload_body_revoke_keeps_file_unwritten(tmp_path):
    worker, access = worker_at(tmp_path), CurrentAccess()
    worker.bind(BINDING.copy())
    await worker.control.take(CONTROLLER)
    release = asyncio.Event()

    async def body():
        yield b"first bytes"
        await release.wait()
        yield b"last bytes"

    context = {
        "binding": BINDING,
        "controller": CONTROLLER,
        "controlEpoch": 1,
        "targetEpoch": 0,
    }
    headers = {
        "X-ADB-Browser-Context": quote(json.dumps(context)),
        "X-ADB-Browser-File-Name": "fixture.txt",
    }
    async with serving(worker, host_authorization=access) as (http, origin):
        task = asyncio.create_task(
            http.post(origin + "/files/receive", data=body(), headers=headers)
        )
        await access.created.wait()
        access.allowed = False
        release.set()
        async with await task as response:
            assert response.status == 409
            assert await response.json() == {"error": "browser_authorization_denied"}
    assert not worker.files._index
    assert not list(worker.files.uploads.iterdir())
    assert access.observed[0][2] == {
        "kind": "receive-file",
        "name": "fixture.txt",
        "controlEpoch": 1,
        "targetEpoch": 0,
    }


async def test_rebind_postcommit_refusal_keeps_actual_new_binding_and_human_lease(
    tmp_path,
):
    worker = worker_at(tmp_path)
    await with_page(worker)
    target = {**BINDING, "sessionId": "new-original-run"}

    async def factory(request, binding, controller, action):
        assert binding == target
        assert action["previousSessionId"] == BINDING["sessionId"]

        async def check():
            if worker.binding == target:
                raise PermissionError("grant withdrew after original journal commit")

        return check

    async with serving(worker, host_authorization=factory) as (http, origin):
        async with http.post(
            origin + "/invoke",
            json={
                "binding": target,
                "controller": CONTROLLER,
                "action": {
                    "kind": "bind-session",
                    "previousSessionId": BINDING["sessionId"],
                },
            },
        ) as response:
            assert response.status == 409
            assert await response.json() == {"error": "browser_authorization_denied"}
    assert worker.binding == target
    assert json.loads(worker.journal.read_text())["binding"] == target
    assert worker.control.state == "human"
    assert worker.control.controller == CONTROLLER


async def test_direct_managed_invoke_cannot_bypass_required_assertion(tmp_path):
    worker = worker_at(tmp_path)
    with pytest.raises(ControlError, match="^browser_authorization_required$"):
        await worker.invoke(CONTROLLER, {"kind": "state"})
    await worker.close()


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/files/receive"),
        ("POST", "/files/read"),
        ("GET", "/window-stream"),
    ],
)
async def test_managed_file_and_view_routes_cannot_bypass_assertion(
    tmp_path, method, path
):
    worker = worker_at(tmp_path)
    context = {
        "binding": BINDING,
        "controller": CONTROLLER,
        "controlEpoch": 0,
        "targetEpoch": 0,
        "viewerId": "viewer",
        "fileId": "0" * 32,
    }
    async with serving(worker) as (http, origin):
        async with http.request(
            method,
            origin + path,
            data=b"fixture",
            headers={
                "X-ADB-Browser-Context": quote(json.dumps(context)),
                "X-ADB-Browser-File-Name": "fixture.txt",
            },
        ) as response:
            assert response.status == 409
            assert await response.json() == {"error": "browser_authorization_required"}
    assert worker.binding is None
    assert not worker.journal.exists()
    assert not worker.files._index


async def test_start_rechecks_after_extension_preparation_before_next_effect(
    tmp_path, monkeypatch
):
    from ai_dev_browser.remote import worker as module

    worker, access = worker_at(tmp_path), CurrentAccess()
    extension = tmp_path / "fixture-extension"
    extension.mkdir()
    (extension / "identity.json").write_text(
        json.dumps({"id": "fixture", "version": "1"})
    )
    worker.extension_directory = extension
    effects = []

    async def prepared(*args, **kwargs):
        effects.append("original profile preparation")
        access.allowed = False

    async def file_access(*args, **kwargs):
        effects.append("must not configure files")

    def launch(**kwargs):
        effects.append("must not launch")

    monkeypatch.setattr(module, "prepare_managed_extension_profile", prepared)
    monkeypatch.setattr(module, "configure_managed_extension_file_access", file_access)
    monkeypatch.setattr(module, "browser_start", launch)
    async with serving(worker, host_authorization=access) as (http, origin):
        async with http.post(
            origin + "/invoke",
            json=request(
                {
                    "kind": "start",
                    "isHeadless": True,
                    "transport": "extension",
                }
            ),
        ) as response:
            assert response.status == 409
            assert await response.json() == {"error": "browser_authorization_denied"}
    assert effects == ["original profile preparation"]
    assert worker.browser is None and worker.session is None
    assert worker.control.controller == CONTROLLER


async def test_post_launch_refusal_retains_owned_identity_and_requires_recovery(
    tmp_path, monkeypatch
):
    from ai_dev_browser.remote import worker as module

    worker, access = worker_at(tmp_path), CurrentAccess()
    effects = []

    def launch(**kwargs):
        effects.append("one original launch")
        access.allowed = False
        return {"session_id": "original-owned-launch", "pid": 12345}

    def stop(*, session_id):
        effects.append(("cleanup", session_id))
        return {"stopped": True}

    async def connect(**kwargs):
        effects.append("must not connect after withdrawal")

    monkeypatch.setattr(module, "browser_start", launch)
    monkeypatch.setattr(module, "browser_stop", stop)
    monkeypatch.setattr(module, "connect_browser", connect)
    async with serving(worker, host_authorization=access) as (http, origin):
        async with http.post(
            origin + "/invoke",
            json=request(
                {
                    "kind": "start",
                    "isHeadless": True,
                    "transport": "cdp",
                }
            ),
        ) as response:
            assert response.status == 409
            assert await response.json() == {"error": "browser_authorization_denied"}
        assert worker.browser["session_id"] == "original-owned-launch"
        assert worker.control.state == "error"
        assert worker.control.controller == CONTROLLER
        assert worker.control.error == "browser_restart_requires_observation"
        assert effects == ["one original launch"]
    assert effects == ["one original launch", ("cleanup", "original-owned-launch")]
