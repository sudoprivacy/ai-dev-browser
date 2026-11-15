"""Real original Worker HTTP/session/Chrome; host authority/writer are fixtures."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import aiohttp
from aiohttp import web
import pytest

from ai_dev_browser.core import _session
from ai_dev_browser.remote.worker import Worker, application


async def serve(app):
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"


async def worker_recording_journey(tmp_path, monkeypatch, *, extension=False):
    async def form(request):
        return web.Response(
            text='<!doctype html><meta charset="utf-8"><title>Original recorder</title><label>Query<input id="query" name="query" style="width:200px;height:36px"></label>',
            content_type="text/html",
        )

    site = web.Application()
    site.router.add_get("/form", form)
    site_runner, website = await serve(site)
    parent = os.environ.get("AI_DEV_BROWSER_CAPTURE_PRIVATE_ROOT")
    if parent:
        Path(parent).mkdir(parents=True, exist_ok=True)
    source_entered, source_release = asyncio.Event(), asyncio.Event()
    sink_entered, sink_release = asyncio.Event(), asyncio.Event()
    calls = []
    frame_count = 0
    binding = {
        "orgId": "fixture-org",
        "userId": "fixture-human",
        "sessionId": "original-browser-only",
    }
    controller = "user-fixture"
    checks = []
    with tempfile.TemporaryDirectory(
        prefix="adb-worker-record-private-", dir=parent
    ) as private:
        private = Path(private)
        monkeypatch.setattr(_session, "_DIR", private / "native-sessions")
        worker = Worker(
            private / "profile",
            "host-fixture",
            "agent-fixture",
            display_mode="native",
            chrome_path=os.environ.get("AI_DEV_BROWSER_CHROME"),
            chrome_args=["--no-sandbox"] if sys.platform == "linux" else [],
            require_host_authorization=True,
            existing_extension_root=private / "personal-leases" if extension else None,
        )

        async def authority(request, original_binding, actor, action):
            nonlocal frame_count
            assert original_binding == binding and actor == controller
            if action["kind"] == "record-frame":
                assert (
                    action["targetId"]
                    and action["frameId"]
                    and action["contextUniqueId"]
                )
                assert action["origin"] in {website, "", "://"}
                frame_count += 1
                if frame_count == 3:
                    source_entered.set()
                    await source_release.wait()

            async def current():
                if worker.binding is None:
                    assert worker.session is None and worker.browser is None
                else:
                    assert worker.binding == binding

            return current

        async def sink(request, original_binding, actor, payload):
            assert original_binding == binding and actor == controller
            assert payload["recordingId"] in {
                "original-recording",
                "uncertain-recording",
            }
            calls.append(payload["recordingId"])
            if payload["recordingId"] == "original-recording":
                sink_entered.set()
                await sink_release.wait()

            def write():
                path = private / (payload["recordingId"] + ".json")
                with path.open("xb") as output:
                    output.write(
                        json.dumps(
                            payload,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        ).encode()
                    )
                    output.flush()
                    os.fsync(output.fileno())

            await asyncio.to_thread(write)
            if payload["recordingId"] == "uncertain-recording":
                raise ConnectionError(
                    "fixture persistence reply lost after actual fsync"
                )

        async def reconcile(request, original_binding, actor, payload, digest):
            assert original_binding == binding and actor == controller
            data = await asyncio.to_thread(
                (private / (payload["recordingId"] + ".json")).read_bytes
            )
            assert hashlib.sha256(data).hexdigest() == digest
            assert json.loads(data) == payload

        sdk_runner, origin = await serve(
            application(
                worker,
                host_authorization=authority,
                recording_sink=sink,
                recording_reconcile=reconcile,
            )
        )
        async with aiohttp.ClientSession(
            headers={"Authorization": "Bearer host-fixture"},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as http:

            async def invoke(action, status=200):
                action = {
                    **(
                        {
                            "controlEpoch": worker.control.epoch,
                            "targetEpoch": worker.control.target_epoch,
                        }
                        if action["kind"]
                        not in {
                            "start",
                            "state",
                            "inspect-existing-extension",
                            "connect-existing-extension",
                        }
                        else {}
                    ),
                    **action,
                }
                async with http.post(
                    origin + "/invoke",
                    json={
                        "binding": binding,
                        "controller": controller,
                        "action": action,
                    },
                ) as response:
                    data = await response.json()
                    assert response.status == status, data.get("error")
                    return data

            async def input_value(value):
                page = await worker.session._connect_page()
                point = await page.js(
                    '(()=>{const r=document.querySelector("#query").getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()'
                )
                await invoke({"kind": "input", "input": {"kind": "click", **point}})
                await invoke(
                    {"kind": "input", "input": {"kind": "text", "text": value}}
                )

            try:
                if extension:
                    selected = (await invoke({"kind": "inspect-existing-extension"}))[
                        "existingExtension"
                    ]
                    await invoke({"kind": "connect-existing-extension", **selected})
                    assert worker.session.files is None
                    state = (await invoke({"kind": "state"}))["session"]
                    assert state["capabilities"]["fileTransfer"] is False
                else:
                    await invoke(
                        {"kind": "start", "isHeadless": True, "transport": "cdp"}
                    )
                original_browser = worker.browser
                values = (
                    ["same recorded value"] * 2
                    if extension
                    else ["first original tab", "second original tab"]
                )
                await invoke({"kind": "navigate", "url": website + "/form"})
                first_target = worker.session.target_id
                await invoke(
                    {"kind": "record-start", "recordingId": "original-recording"}
                )
                await input_value(values[0])
                await invoke({"kind": "new-tab"})
                second_target = worker.session.target_id
                assert first_target != second_target
                await invoke({"kind": "navigate", "url": website + "/form"})
                await asyncio.wait_for(source_entered.wait(), 10)
                pending = asyncio.create_task(input_value(values[1]))
                await asyncio.sleep(0.05)
                assert not pending.done()
                source_release.set()
                await pending
                checks.extend(
                    [
                        "existing Worker starts original SDK Chrome without another recording browser",
                        "same recording follows actual selected tab and native document",
                        "SDK input waits for new document recording admission",
                    ]
                )
                stopped = asyncio.create_task(
                    invoke({"kind": "record-stop", "recordingId": "original-recording"})
                )
                await asyncio.wait_for(sink_entered.wait(), 10)
                assert (
                    not stopped.done()
                    and not (private / "original-recording.json").exists()
                )
                sink_release.set()
                reply = await stopped
                assert reply["recording"]["storageStatus"] == "saved"
                saved = json.loads((private / "original-recording.json").read_bytes())
                events = saved["snapshot"]["events"]
                assert any(
                    e.get("value") == values[0] and e["targetId"] == first_target
                    for e in events
                )
                assert any(
                    e.get("value") == values[1] and e["targetId"] == second_target
                    for e in events
                )
                assert len(saved["sources"]) >= 3 and saved["draft"]
                steps = saved["draft"]["steps"]["steps"]
                tabs = [step for step in steps if step["kind"] == "new_tab"]
                assert len(tabs) == 1 and tabs[0]["target"]["targetId"] == second_target
                assert [
                    step["target"]["targetId"]
                    for step in steps
                    if step["kind"] == "fill"
                ] == [first_target, second_target]
                checks.append(
                    "last values on both targets durably stored before Stop result"
                )
                await invoke(
                    {"kind": "record-stop", "recordingId": "original-recording"}
                )
                assert (
                    calls == ["original-recording"]
                    and worker.browser is original_browser
                )
                assert (
                    worker.control.controller == controller
                    and worker.control.state == "human"
                )
                checks.append(
                    "repeated Stop reads original result, browser and human lease retained"
                )
                await invoke(
                    {"kind": "record-start", "recordingId": "uncertain-recording"}
                )
                await input_value("uncertain final value")
                unknown = await invoke(
                    {"kind": "record-stop", "recordingId": "uncertain-recording"},
                    status=409,
                )
                assert unknown["error"] == "browser_recording_write_unconfirmed"
                assert (private / "uncertain-recording.json").exists()
                recovered = await invoke(
                    {"kind": "record-stop", "recordingId": "uncertain-recording"}
                )
                assert recovered["recording"]["storageStatus"] == "saved"
                assert calls == ["original-recording", "uncertain-recording"]
                checks.append(
                    "actual committed-then-lost save reconciled by read/digest without second persistence"
                )
                assert (
                    worker.browser is original_browser
                    and worker.session.target_id == second_target
                )
                if extension:
                    assert worker.session.files is None
                    await invoke({"kind": "disconnect-existing-extension"})
                else:
                    await invoke({"kind": "stop"})
                assert worker.session is None and worker.browser is None
                checks.append(
                    "original managed lifecycle closes only after retained terminal outcome"
                )
                safe = {
                    "checks": checks,
                    "storedRecordings": 2,
                    "persistenceCalls": len(calls),
                    "firstTerminalSha256": hashlib.sha256(
                        (private / "original-recording.json").read_bytes()
                    ).hexdigest(),
                    "actualWorkerHttpChromeAndFsync": True,
                    "transport": "extension" if extension else "cdp",
                    "equalValuesAcrossDistinctNativeTargets": extension,
                    "personalFileTransferUnavailable": extension,
                    "syntheticHostGrantAndWriterCallbacks": True,
                    "mossworkStoreCanonicalProviderNativeJoinsOrProduction": False,
                }
                (tmp_path / "worker-recording-observation.json").write_text(
                    json.dumps(safe, indent=2) + "\n", encoding="utf-8"
                )
            finally:
                source_release.set()
                sink_release.set()
                await sdk_runner.cleanup()
                await site_runner.cleanup()


async def test_existing_worker_records_tab_switch_and_durable_terminal_once(
    tmp_path, monkeypatch
):
    await worker_recording_journey(tmp_path, monkeypatch)


async def extension_recording_child(tmp_path):
    with pytest.MonkeyPatch.context() as patch:
        await worker_recording_journey(tmp_path, patch, extension=True)


async def test_existing_extension_worker_records_distinct_tabs_and_durable_terminal_once(
    live_extension, tmp_path
):
    env = {
        **os.environ,
        "AI_DEV_BROWSER_EXTENSION_BRIDGE_PORT": str(live_extension.port),
    }
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import asyncio,sys;from pathlib import Path;"
        "from tests.integration.test_worker_recording_live import extension_recording_child;"
        "asyncio.run(extension_recording_child(Path(sys.argv[1])))",
        str(tmp_path),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), 90)
        (tmp_path / "recording-worker-child.log").write_bytes(output)
        assert process.returncode == 0, output.decode("utf-8", errors="replace")
        evidence = json.loads(
            (tmp_path / "worker-recording-observation.json").read_text(encoding="utf-8")
        )
        assert (
            evidence["transport"] == "extension" and evidence["persistenceCalls"] == 2
        )
        assert evidence["equalValuesAcrossDistinctNativeTargets"]
        assert evidence["personalFileTransferUnavailable"]
    finally:
        if process.returncode is None:
            process.terminate()
            await asyncio.wait_for(process.wait(), 10)
