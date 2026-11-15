"""Owned capture lifecycle with explicit fixture grants and a page transport."""

import asyncio
import json
import re

import pytest

from ai_dev_browser.record.capture import EventRecording
from ai_dev_browser.remote.control import ControlError


async def allowed():
    return None


class Grants:
    def __init__(self):
        self.allowed = True
        self.denied_frames = set()
        self.scopes = []

    async def __call__(self, target, frame, context, unique_id, origin):
        self.scopes.append((target, frame, context, unique_id, origin))

        async def check():
            if not self.allowed or frame in self.denied_frames:
                raise PermissionError("private fixture source grant")

        return check


class Page:
    """Protocol fixture only: real TCP/Chrome is qualified separately."""

    def __init__(self):
        self.disconnected = False
        self.reader = asyncio.get_running_loop().create_future()
        self.handlers = set()
        self.calls = []
        self.world = ""
        self.binding = ""
        self.config = {}
        self.sequences = {}
        self.context_ids = {}
        self.nonces = {}
        self.started = set()
        self.stopped = []
        self.pending_input = None
        self.install_entered = asyncio.Event()
        self.install_release = None

    def add_event_handler(self, handler):
        self.handlers.add(handler)

    def remove_event_handler(self, handler):
        found = handler in self.handlers
        self.handlers.discard(handler)
        return found

    def emit(self, method, params):
        for handler in tuple(self.handlers):
            handler(method, params)

    def context(self, identity, frame, origin, unique_id=None):
        unique_id = unique_id or ("native-document-" + str(identity))
        self.context_ids[unique_id] = identity
        self.emit(
            "Runtime.executionContextCreated",
            {
                "context": {
                    "id": identity,
                    "uniqueId": unique_id,
                    "name": self.world,
                    "origin": origin,
                    "auxData": {"frameId": frame},
                }
            },
        )

    def event(self, kind, *, context=1, **values):
        sequence = self.sequences.get(context, 0) + 1
        self.sequences[context] = sequence
        payload = {
            "nonce": self.config["nonce"],
            "contextNonce": self.nonces[context],
            "schemaVersion": "1.0",
            "event": {
                "localSeq": sequence,
                "kind": kind,
                "page": {"url": "https://original.example/form"},
                **values,
            },
        }
        self.emit(
            "Runtime.bindingCalled",
            {
                "name": self.binding,
                "executionContextId": context,
                "payload": json.dumps(payload),
            },
        )
        return payload

    async def call(self, method, params=None, timeout=20):
        params = params or {}
        self.calls.append((method, params))
        if method == "Page.getFrameTree":
            return {
                "frameTree": {
                    "frame": {
                        "id": "root",
                        "url": "https://original.example/form",
                        "securityOrigin": "https://original.example",
                    }
                }
            }
        if method == "Runtime.addBinding":
            self.binding = params["name"]
        elif method == "Page.createIsolatedWorld":
            self.world = params["worldName"]
            assert params["grantUniveralAccess"] is False
            self.context(1, "root", "https://original.example")
            return {"executionContextId": 1}
        elif method == "Page.addScriptToEvaluateOnNewDocument":
            self.install_entered.set()
            if self.install_release:
                await self.install_release.wait()
            return {"identifier": "owned-script"}
        elif method == "Runtime.evaluate":
            expression = params["expression"]
            assert "contextId" not in params
            identity = self.context_ids[params["uniqueContextId"]]
            starting = re.search(
                r'globalThis\.__adbSemanticRecorder\.start\(("[a-z0-9]+")\);$',
                expression,
            )
            if starting:
                self.nonces[identity] = json.loads(starting[1])
                self.config = json.loads(
                    expression.split("\n", 1)[0]
                    .removeprefix("globalThis.__ADB_RECORD_CONFIG__ = ")
                    .removesuffix(";")
                )
                if identity not in self.started:
                    self.started.add(identity)
                    self.event("recorder_installed", context=identity)
            elif "__adbSemanticRecorder?.stop(" in expression:
                flush = ".stop(true)" in expression
                self.stopped.append((identity, flush))
                if flush and self.pending_input and identity == 1:
                    self.event(
                        "input",
                        value=self.pending_input,
                        target={"name": "Search", "tag": "input"},
                    )
                    self.pending_input = None
                self.started.discard(identity)
        return {}

    def finish(self):
        self.disconnected = True
        if not self.reader.done():
            self.reader.set_result(None)


async def active(**limits):
    capture, page, grants = (
        EventRecording("original-recording", show_indicator=False, **limits),
        Page(),
        Grants(),
    )
    await capture.attach_source(
        "original-target", page, before_effect=allowed, authorize_frame=grants
    )
    return capture, page, grants


async def test_missing_capture_assertion_never_installs_or_claims_recording():
    capture, page = EventRecording("original"), Page()
    assert capture.status()["status"] == "starting"
    with pytest.raises(ControlError, match="^browser_authorization_required$"):
        await capture.attach_source(
            "original", page, before_effect=None, authorize_frame=Grants()
        )
    assert page.calls == [] and not page.handlers
    await capture.close()
    page.finish()


async def test_real_source_ids_override_page_claims_and_duplicate_sequences():
    capture, page, grants = await active()
    try:
        original = page.event(
            "input",
            targetId="forged-target",
            value="search terms",
            target={"name": "Search", "framePath": ["forged"]},
        )
        page.emit(
            "Runtime.bindingCalled",
            {
                "name": page.binding,
                "executionContextId": 1,
                "payload": json.dumps(original),
            },
        )
        result = await capture.snapshot(before_read=allowed)
        assert len(result["events"]) == 2
        event = result["events"][-1]
        assert event["targetId"] == "original-target" and event["frameId"] == "root"
        assert event["page"]["origin"] == "https://original.example"
        assert event["target"]["framePath"] == []
        assert grants.scopes == [
            (
                "original-target",
                "root",
                1,
                "native-document-1",
                "https://original.example",
            )
        ]
    finally:
        await capture.close()
        assert not page.handlers and not page.reader.done()
        page.finish()


async def test_each_iframe_gets_its_own_assertion_before_any_collection():
    capture, page, grants = await active()
    try:
        page.context(2, "child", "https://child.example")
        await capture.drain()
        page.event(
            "change", context=2, value="child value", target={"name": "Child field"}
        )
        result = await capture.snapshot(before_read=allowed)
        event = result["events"][-1]
        assert event["frameId"] == "child"
        assert event["target"]["framePath"] == ["https://child.example"]
        assert grants.scopes[-1] == (
            "original-target",
            "child",
            2,
            "native-document-2",
            "https://child.example",
        )
    finally:
        await capture.close()
        page.finish()


async def test_denied_iframe_never_starts_its_dom_reader():
    capture, page, grants = await active()
    grants.denied_frames.add("child")
    page.context(2, "child", "https://private.example")
    with pytest.raises(ControlError, match="^browser_authorization_denied$"):
        await capture.drain()
    status = await capture.close()
    assert status["status"] == "failed"
    assert not any(
        method == "Runtime.evaluate"
        and params["uniqueContextId"] == "native-document-2"
        and "globalThis.__adbSemanticRecorder.start(" in params["expression"]
        for method, params in page.calls
    )
    assert not page.handlers and not page.reader.done()
    page.finish()


async def test_revocation_after_capture_withholds_event_and_snapshot():
    capture, page, grants = await active()
    grants.allowed = False
    page.event("input", value="withheld", target={"name": "Search"})
    with pytest.raises(ControlError, match="^browser_authorization_denied$"):
        await capture.snapshot(before_read=allowed)
    await capture.close()
    assert capture.status()["events"] == 1
    assert page.stopped == [(1, False)]
    assert not page.handlers
    page.finish()


async def test_stop_flushes_last_debounced_input_and_preserves_page():
    capture, page, _ = await active()
    page.pending_input = "last user value"
    status = await capture.close()
    assert status["status"] == "stopped" and status["events"] == 2
    assert (await capture.snapshot(before_read=allowed))["events"][-1][
        "value"
    ] == "last user value"
    assert page.stopped == [(1, True)]
    assert not page.handlers and not page.reader.done()
    methods = [method for method, _ in page.calls]
    assert "Page.removeScriptToEvaluateOnNewDocument" in methods
    assert "Runtime.removeBinding" in methods
    assert "Page.close" not in methods and "Browser.close" not in methods
    page.finish()


async def test_source_disconnect_is_failed_without_reconnect_or_success():
    capture, page, _ = await active()
    page.finish()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    status = await capture.close()
    assert status["status"] == "failed"
    assert status["error"] == "browser_recording_disconnected"
    assert status["cleanupUncertain"] is True
    assert not page.handlers


async def test_cancelled_initialization_drains_late_install_then_retires_it():
    capture, page, grants = EventRecording("original"), Page(), Grants()
    page.install_release = asyncio.Event()
    pending = asyncio.create_task(
        capture.attach_source(
            "original-target", page, before_effect=allowed, authorize_frame=grants
        )
    )
    await page.install_entered.wait()
    pending.cancel()
    await asyncio.sleep(0)
    assert not pending.done()
    page.install_release.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert capture.status()["status"] == "failed"
    assert not page.started and not page.handlers
    assert not page.reader.done()
    page.finish()


async def test_read_denial_and_scope_change_never_release_a_snapshot():
    capture, page, _ = await active()

    async def denied():
        raise PermissionError("private current read grant")

    with pytest.raises(ControlError, match="^browser_authorization_denied$"):
        await capture.snapshot(before_read=denied)

    async def changed():
        page.context(2, "new-child", "https://child.example")
        await capture.drain()

    with pytest.raises(ControlError, match="^browser_recording_sources_changed$"):
        await capture.snapshot(before_read=changed)
    await capture.close()
    page.finish()


async def test_limits_fail_without_silently_returning_a_partial_workflow():
    capture, page, _ = await active(max_events=1)
    page.event("input", value="over limit", target={"name": "Search"})
    with pytest.raises(ControlError, match="^browser_recording_limit$"):
        await capture.snapshot(before_read=allowed)
    await capture.close()
    assert capture.status()["events"] == 1 and not page.handlers
    page.finish()


async def test_reused_numeric_context_requires_new_document_admission():
    capture, page, grants = await active()
    try:
        page.emit("Runtime.executionContextDestroyed", {"executionContextId": 1})
        page.started.discard(1)
        page.sequences.pop(1)
        page.context(
            1, "root", "https://next.example", unique_id="next-native-document"
        )
        await capture.drain()
        assert len(grants.scopes) == 2
        assert grants.scopes[-1][-1] == "https://next.example"
        snapshot = await capture.snapshot(before_read=allowed)
        assert snapshot["events"][-1]["page"]["origin"] == "https://next.example"
    finally:
        await capture.close()
        page.finish()


async def test_late_old_document_event_cannot_enter_reused_numeric_context():
    capture, page, _ = await active()
    try:
        old = page.event(
            "input", value="original accepted input", target={"name": "Search"}
        )
        await capture.drain()
        page.emit("Runtime.executionContextDestroyed", {"executionContextId": 1})
        page.started.discard(1)
        page.sequences.pop(1)
        page.context(1, "root", "https://next.example", unique_id="new-document")
        await capture.drain()
        before = (await capture.snapshot(before_read=allowed))["events"]
        old["event"]["localSeq"] = 2
        old["event"]["value"] = "late old document secret"
        page.emit(
            "Runtime.bindingCalled",
            {"name": page.binding, "executionContextId": 1, "payload": json.dumps(old)},
        )
        after = (await capture.snapshot(before_read=allowed))["events"]
        assert after == before
        page.event("input", value="new current input", target={"name": "Search"})
        current = (await capture.snapshot(before_read=allowed))["events"][-1]
        assert current["value"] == "new current input"
        assert current["page"]["origin"] == "https://next.example"
    finally:
        await capture.close()
        page.finish()


async def test_new_document_does_not_reuse_old_assertion_after_authorization_wait():
    capture, page, grants = await active()
    entered, release = asyncio.Event(), asyncio.Event()
    original = grants.__call__

    async def waiting(target, frame, context, unique_id, origin):
        assertion = await original(target, frame, context, unique_id, origin)
        if unique_id == "old-child-document":
            entered.set()
            await release.wait()
        return assertion

    capture._sources["original-target"].authorize = waiting
    try:
        page.context(2, "child", "https://old.example", unique_id="old-child-document")
        await entered.wait()
        page.emit("Runtime.executionContextDestroyed", {"executionContextId": 2})
        page.context(
            2, "child", "https://current.example", unique_id="current-child-document"
        )
        release.set()
        await capture.drain()
        evaluations = [
            params
            for method, params in page.calls
            if method == "Runtime.evaluate"
            and "globalThis.__adbSemanticRecorder.start(" in params["expression"]
        ]
        assert not any(
            value["uniqueContextId"] == "old-child-document" for value in evaluations
        )
        assert any(
            value["uniqueContextId"] == "current-child-document"
            for value in evaluations
        )
    finally:
        release.set()
        await capture.close()
        page.finish()


async def test_oversize_binding_is_refused_before_it_enters_the_capture_queue():
    capture, page, _ = await active()
    page.emit(
        "Runtime.bindingCalled",
        {
            "name": page.binding,
            "executionContextId": 1,
            "payload": "x" * (64 * 1024 + 1),
        },
    )
    assert capture._queue.empty()
    with pytest.raises(ControlError, match="^browser_recording_event_invalid$"):
        await capture.snapshot(before_read=allowed)
    assert (await capture.close())["status"] == "failed"
    assert capture.status()["events"] == 1 and not page.handlers
    page.finish()
