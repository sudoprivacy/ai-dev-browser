"""Original SDK Chrome, semantic refs and files; grants/website are fixtures."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

import aiohttp
from aiohttp import web
import pytest

from ai_dev_browser.core import _session
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.connection import connect_browser
from ai_dev_browser.record.replay import CheckedReplay
from ai_dev_browser.remote.control import ControlError
from ai_dev_browser.remote.files import BrowserFiles
from ai_dev_browser.remote.session import BrowserSession


async def test_original_sdk_checked_replay_parameters_files_tabs_and_single_write(
    tmp_path, monkeypatch
):
    writes = []
    committed = asyncio.Event()
    navigation_transition = {"enabled": False, "admitted": False}

    async def form(request):
        return web.Response(
            content_type="text/html",
            text="""<!doctype html><meta charset="utf-8"><title>Original SDK replay</title>
        <style>body{margin:12px}label{display:block;margin:10px}input,select,button{min-height:28px}</style>
        <label>Search<input id="query" name="query"></label>
        <label>Other<input id="other" name="other"></label>
        <label><input id="enabled" type="checkbox" checked>Enabled</label>
        <label>Choice<select id="choice"><option value="a">First</option><option value="b">Second</option></select></label>
        <label>Upload<input id="file" type="file"></label>
        <button id="commit">Commit once</button><button>Repeat</button><button>Repeat</button>
        <script>window.replayInputEvents=[];
        window.addEventListener('unhandledrejection',e=>{window.fixtureErrorName=e.reason?.name||'unknown'});
        for(const kind of ['focusin','beforeinput','input','keydown','keyup','change']) document.addEventListener(kind,e=>replayInputEvents.push({kind:e.type,id:e.target.id}),true);
        document.querySelector('#commit').onclick=async()=>{
          const file=document.querySelector('#file').files[0];
          const r=await fetch('/commit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
            query:document.querySelector('#query').value,enabled:document.querySelector('#enabled').checked,
            choice:document.querySelector('#choice').value,file:file?await file.text():null})});
          if(r.ok) location.href='/done';
        };</script>""",
        )

    async def commit(request):
        writes.append(await request.json())
        committed.set()
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_get("/form", form)
    app.router.add_post("/commit", commit)

    async def done(request):
        return web.Response(
            text="<title>Done</title><h1>Committed</h1>", content_type="text/html"
        )

    app.router.add_get("/done", done)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    origin = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    parent = os.environ.get("AI_DEV_BROWSER_CAPTURE_PRIVATE_ROOT")
    if parent:
        Path(parent).mkdir(parents=True, exist_ok=True)
    client = launched = session = None
    checks = []
    grant = {"allowed": True}
    requests = []
    focus_race = {"after_select": False, "armed": False, "moved": False}
    pointer_race = {"enabled": False, "armed": False, "moved": False}
    meaning_race = {"after_select": False, "armed": False, "changed": False}

    async def current():
        if not grant["allowed"]:
            raise PermissionError("explicit fixture source grant")
        if focus_race["armed"]:
            focus_race["armed"] = False
            focus_race["moved"] = True
            await page.js("document.querySelector('#other').focus()")
        if pointer_race["armed"]:
            pointer_race["armed"] = False
            pointer_race["moved"] = True
            await page.js("""(()=>{
                const button=document.querySelector('#commit'), r=button.getBoundingClientRect();
                const trap=document.createElement('button'); trap.id='trap'; trap.textContent='Different action';
                trap.style.cssText=`position:fixed;left:${r.left}px;top:${r.top}px;width:${r.width}px;height:${r.height}px`;
                window.trapClicks=0; trap.onclick=()=>window.trapClicks++;
                button.style.cssText=`position:fixed;left:${r.left+300}px;top:${r.top}px`;
                document.body.append(trap);
            })()""")
        if meaning_race["armed"]:
            meaning_race["armed"] = False
            meaning_race["changed"] = True
            await page.js("document.querySelector('#query').type='password'")

    async def authorize(recording, step, target, frame):
        assert recording == "original-recording" and target
        if frame is not None:
            own_blank = (
                frame["url"] == "about:blank"
                and step["kind"] == "open"
                and step.get("url", "").startswith(origin + "/")
                and session is not None
                and target
                in {str(tab._target.target_id) for tab in session.browser.tabs}
            )
            assert frame["origin"] == origin or own_blank
        requests.append((step["kind"], frame is not None))
        if (
            navigation_transition["enabled"]
            and step["kind"] == "verify"
            and frame is not None
            and not navigation_transition["admitted"]
            and frame["url"].startswith(origin + "/form")
        ):
            # The verifier has observed the old document. An independent native
            # navigation commits during the actual current-authority await.
            navigation = await page.call("Page.navigate", {"url": origin + "/done"})
            await page.wait_navigation(navigation)
            navigation_transition["admitted"] = True
        return current

    with tempfile.TemporaryDirectory(
        prefix="adb-replay-private-", dir=parent
    ) as private:
        monkeypatch.setattr(_session, "_DIR", Path(private) / "sessions")
        try:
            launched = await asyncio.to_thread(
                browser_start,
                headless=True,
                temp=True,
                stealth=False,
                transport="cdp",
                url=origin + "/form",
                chrome_path=os.environ.get("AI_DEV_BROWSER_CHROME"),
                silent_stderr=True,
                extra_args=["--no-sandbox"] if sys.platform == "linux" else [],
            )
            assert "error" not in launched, {"error_code": launched.get("error_code")}
            client = await connect_browser(session_id=launched["session_id"])
            async with aiohttp.ClientSession() as http:
                files = BrowserFiles(Path(private) / "files")
                upload = files.receive("original.txt", b"original owned file")
                session = BrowserSession(client, http, files=files)
                initial = await session.state(before_effect=current)
                target = initial["activeTargetId"]
                await session.take(
                    "original-human",
                    initial["controlEpoch"],
                    initial["targetEpoch"],
                    before_effect=current,
                )
                page = await session._connect_page()

                def replay(operation):
                    return CheckedReplay(
                        session,
                        operation,
                        actor="original-human",
                        control_epoch=session.control.epoch,
                        target_epoch=session.control.target_epoch,
                        target_bindings={"recorded-page": target},
                        authorize_step=authorize,
                    )

                doc = {
                    "schemaVersion": "1.0",
                    "recordingId": "original-recording",
                    "inputs": [
                        {"name": "query", "required": True},
                        {"name": "owned_file", "kind": "file", "required": True},
                    ],
                    "steps": [
                        {
                            "id": "open",
                            "kind": "open",
                            "url": origin + "/form",
                            "target": {"targetId": "recorded-page"},
                        },
                        {
                            "id": "fill",
                            "kind": "fill",
                            "value": "{{query}}",
                            "target": {
                                "id": "query",
                                "name": "Search",
                                "role": "textbox",
                                "targetId": "recorded-page",
                                "ref": "999#999",
                                "bbox": {"x": 0, "y": 0},
                            },
                        },
                        {
                            "id": "key",
                            "kind": "press",
                            "key": "Tab",
                            "target": {
                                "id": "query",
                                "name": "Search",
                                "role": "textbox",
                                "targetId": "recorded-page",
                            },
                        },
                        {
                            "id": "uncheck",
                            "kind": "set_checked",
                            "value": "false",
                            "target": {
                                "id": "enabled",
                                "role": "checkbox",
                                "targetId": "recorded-page",
                            },
                        },
                        {
                            "id": "select",
                            "kind": "select",
                            "value": "b",
                            "target": {
                                "id": "choice",
                                "role": "combobox",
                                "targetId": "recorded-page",
                            },
                        },
                        {
                            "id": "file",
                            "kind": "upload",
                            "value": "{{owned_file}}",
                            "target": {"id": "file", "targetId": "recorded-page"},
                        },
                        {
                            "id": "commit",
                            "kind": "click",
                            "target": {
                                "id": "commit",
                                "name": "Commit once",
                                "role": "button",
                                "targetId": "recorded-page",
                            },
                            "expect": {"urlContains": "/done"},
                        },
                    ],
                    "verification": [
                        {"type": "url_contains", "value": "/done"},
                        {"type": "title_contains", "value": "Done"},
                        {"type": "text_contains", "value": "Committed"},
                        {"type": "selector_exists", "value": "h1"},
                    ],
                }
                original = json.loads(json.dumps(doc))
                positive = replay("original-operation")
                try:
                    result = await positive.run(
                        doc,
                        {
                            "query": "新参数 & preserved",
                            "owned_file": json.dumps([upload["id"]]),
                        },
                        before_run=current,
                        before_result=current,
                    )
                except Exception:
                    (tmp_path / "replay-failure-status.json").write_text(
                        json.dumps(positive.status(), indent=2), encoding="utf-8"
                    )
                    try:
                        observed = await page.js(
                            "(()=>{const q=document.querySelector('#query'),f=document.querySelector('#file'),b=document.querySelector('#commit');return {path:location.pathname,query:q?.value,enabled:document.querySelector('#enabled')?.checked,choice:document.querySelector('#choice')?.value,files:f?[...f.files].map(f=>({bytes:f.size})):[],active:document.activeElement?.id,button:b?(()=>{const r=b.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}})():null,errorName:window.fixtureErrorName||null};})()"
                        )
                    except Exception as observation_error:
                        observed = {
                            "pageObservationUnavailable": type(
                                observation_error
                            ).__name__
                        }
                    value = observed.pop("query", None)
                    observed.update(
                        querySha256=hashlib.sha256(str(value).encode()).hexdigest(),
                        writesObserved=len(writes),
                    )
                    (tmp_path / "replay-failure-page-observation.json").write_text(
                        json.dumps(observed, indent=2), encoding="utf-8"
                    )
                    raise
                assert result["status"] == "passed" and len(result["steps"]) == 7
                assert writes == [
                    {
                        "query": "新参数 & preserved",
                        "enabled": False,
                        "choice": "b",
                        "file": "original owned file",
                    }
                ]
                assert doc == original and "新参数" not in json.dumps(
                    result, ensure_ascii=False
                )
                checks.extend(
                    [
                        "actual fresh SDK refs override stale recorded ref/bbox",
                        "trusted Unicode fill/current focus and original key operation",
                        "actual false checkbox/native select and owned file bytes",
                        "one committed HTTP write and original navigation/document verification",
                    ]
                )
                assert (
                    session.control.state == "human"
                    and session.control.controller == "original-human"
                )
                assert session.target_id == target and not page.reader.done()
                checks.append("same original SDK session/page and human lease retained")
                tab_doc = {
                    "schemaVersion": "1.0",
                    "recordingId": "original-recording",
                    "steps": [
                        {
                            "id": "new",
                            "kind": "new_tab",
                            "url": origin + "/form",
                            "target": {"targetId": "recorded-new-page"},
                        },
                        {
                            "id": "edit",
                            "kind": "fill",
                            "value": "new tab only",
                            "target": {
                                "id": "query",
                                "role": "textbox",
                                "targetId": "recorded-new-page",
                            },
                        },
                    ],
                    "verification": [
                        {
                            "type": "input_value_equals",
                            "selector": "#query",
                            "value": "new tab only",
                        }
                    ],
                }
                assert (
                    await replay("new-tab-operation").run(
                        tab_doc, {}, before_run=current, before_result=current
                    )
                )["status"] == "passed"
                assert (
                    session.target_id != target
                    and session.control.controller == "original-human"
                )
                checks.append(
                    "explicit new recorded-tab mapping uses existing SDK target selection"
                )
                ambiguous = {
                    "schemaVersion": "1.0",
                    "recordingId": "original-recording",
                    "steps": [
                        {
                            "id": "one",
                            "kind": "click",
                            "target": {"name": "Repeat", "role": "button"},
                        }
                    ],
                }
                with pytest.raises(
                    ControlError, match="^browser_replay_target_ambiguous$"
                ):
                    await replay("ambiguous-operation").run(
                        ambiguous, {}, before_run=current, before_result=current
                    )
                assert len(writes) == 1
                checks.append("actual duplicate DOM candidates refuse before input")
                page = await session._connect_page()
                before = await page.js(
                    "({value:document.querySelector('#query').value,focus:document.activeElement.id,events:replayInputEvents})"
                )
                for field, expected in (
                    ("name", "Password"),
                    ("type", "password"),
                    ("tag", "textarea"),
                ):
                    conflict = {
                        "schemaVersion": "1.0",
                        "recordingId": "original-recording",
                        "steps": [
                            {
                                "id": "conflict",
                                "kind": "fill",
                                "value": "FIXTURE_SECRET_VALUE",
                                "target": {
                                    "id": "query",
                                    "role": "textbox",
                                    field: expected,
                                },
                            }
                        ],
                    }
                    refused = replay("conflicting-field-" + field)
                    with pytest.raises(
                        ControlError, match="^browser_replay_target_not_found$"
                    ):
                        await refused.run(
                            conflict, {}, before_run=current, before_result=current
                        )
                    assert refused.status()["status"] == "failed"
                    assert (
                        await page.js(
                            "({value:document.querySelector('#query').value,focus:document.activeElement.id,events:replayInputEvents})"
                        )
                        == before
                    )
                    assert len(writes) == 1
                checks.append(
                    "reused actual field ID cannot override changed label/type/tag; no focus/clear/input"
                )
                original_call = page.call

                async def move_button_during_authorization(
                    method, params=None, timeout=20
                ):
                    response = await original_call(method, params, timeout=timeout)
                    if (
                        pointer_race["enabled"]
                        and not pointer_race["moved"]
                        and method == "Runtime.callFunctionOn"
                        and "__actionState"
                        in (params or {}).get("functionDeclaration", "")
                    ):
                        pointer_race["armed"] = True
                    return response

                monkeypatch.setattr(page, "call", move_button_during_authorization)
                pointer_race["enabled"] = True
                moved_button = replay("button-moved-during-authorization")
                with pytest.raises(
                    ControlError, match="^browser_replay_target_changed$"
                ):
                    await moved_button.run(
                        {
                            "schemaVersion": "1.0",
                            "recordingId": "original-recording",
                            "steps": [
                                {
                                    "id": "click",
                                    "kind": "click",
                                    "target": {"id": "commit", "role": "button"},
                                }
                            ],
                        },
                        {},
                        before_run=current,
                        before_result=current,
                    )
                assert (
                    pointer_race["moved"]
                    and moved_button.status()["status"] == "failed"
                )
                assert await page.js("window.trapClicks") == 0 and len(writes) == 1
                await page.js(
                    "document.querySelector('#trap').remove();document.querySelector('#commit').style.cssText=''"
                )
                monkeypatch.setattr(page, "call", original_call)
                checks.append(
                    "actual button movement during authorization refuses old click coordinates before input"
                )

                async def move_focus_during_authorization(
                    method, params=None, timeout=20
                ):
                    response = await original_call(method, params, timeout=timeout)
                    params = params or {}
                    if (
                        method == "Input.dispatchKeyEvent"
                        and params.get("type") == "keyUp"
                    ):
                        focus_race["after_select"] = True
                    if (
                        focus_race["after_select"]
                        and not focus_race["moved"]
                        and method == "Runtime.callFunctionOn"
                        and "activeElement" in params.get("functionDeclaration", "")
                    ):
                        # The native focus probe has returned. The next real
                        # host callback yields while the actual site moves focus.
                        focus_race["armed"] = True
                    return response

                monkeypatch.setattr(page, "call", move_focus_during_authorization)
                focused_run = replay("focus-changed-during-authorization")
                focus_doc = {
                    "schemaVersion": "1.0",
                    "recordingId": "original-recording",
                    "steps": [
                        {
                            "id": "fill",
                            "kind": "fill",
                            "value": "FIXTURE_SECRET_VALUE",
                            "target": {"id": "query", "role": "textbox"},
                        }
                    ],
                }
                with pytest.raises(
                    ControlError, match="^browser_replay_write_unconfirmed$"
                ):
                    await focused_run.run(
                        focus_doc, {}, before_run=current, before_result=current
                    )
                assert focus_race["moved"]
                assert focused_run.status()["error"] == "browser_replay_focus_changed"
                assert (
                    await page.js("document.querySelector('#query').value")
                    == before["value"]
                )
                assert await page.js("document.querySelector('#other').value") == ""
                assert len(writes) == 1
                monkeypatch.setattr(page, "call", original_call)
                checks.append(
                    "actual focus movement during current authorization refuses secret input without retry"
                )

                async def change_meaning_during_authorization(
                    method, params=None, timeout=20
                ):
                    response = await original_call(method, params, timeout=timeout)
                    params = params or {}
                    if (
                        method == "Input.dispatchKeyEvent"
                        and params.get("type") == "keyUp"
                    ):
                        meaning_race["after_select"] = True
                    if (
                        meaning_race["after_select"]
                        and not meaning_race["changed"]
                        and method == "Runtime.callFunctionOn"
                        and "activeElement" in params.get("functionDeclaration", "")
                    ):
                        meaning_race["armed"] = True
                    return response

                monkeypatch.setattr(page, "call", change_meaning_during_authorization)
                changed_field = replay("field-type-changed-during-authorization")
                focus_doc["steps"][0]["target"]["type"] = "text"
                with pytest.raises(
                    ControlError, match="^browser_replay_write_unconfirmed$"
                ):
                    await changed_field.run(
                        focus_doc, {}, before_run=current, before_result=current
                    )
                assert meaning_race["changed"]
                assert (
                    changed_field.status()["error"] == "browser_replay_target_changed"
                )
                assert (
                    await page.js("document.querySelector('#query').value")
                    == before["value"]
                )
                assert len(writes) == 1
                await page.js("document.querySelector('#query').type='text'")
                monkeypatch.setattr(page, "call", original_call)
                checks.append(
                    "actual input type mutation during authorization refuses fill on the same native node"
                )
                grant["allowed"] = True
                monkeypatch.setattr(page, "call", original_call)
                navigation_transition["enabled"] = True
                coherent = replay("original-coherent-verification-operation")
                report = await coherent.run(
                    {
                        "schemaVersion": "1.0",
                        "recordingId": "original-recording",
                        "steps": [
                            {"id": "scroll", "kind": "scroll_to", "value": "0,0"}
                        ],
                        "verification": [{"type": "url_contains", "value": "/done"}],
                    },
                    {},
                    before_run=current,
                    before_result=current,
                )
                assert (
                    report["status"] == "passed" and navigation_transition["admitted"]
                )
                assert len(writes) == 1
                checks.append(
                    "actual navigation during current verification admission discards old observation without repeating effects"
                )
                navigation = await page.call("Page.navigate", {"url": origin + "/form"})
                await page.wait_navigation(navigation)
                # Hold the actual release acknowledgement after the real site
                # commits, then withdraw the explicit host grant. No request,
                # response body, protocol result or input is substituted.
                page = await session._connect_page()
                original_call = page.call
                committed.clear()

                async def held_release(method, params=None, timeout=20):
                    response = await original_call(method, params, timeout=timeout)
                    if (
                        method == "Input.dispatchMouseEvent"
                        and params.get("type") == "mouseReleased"
                    ):
                        await asyncio.wait_for(committed.wait(), 10)
                        grant["allowed"] = False
                    return response

                monkeypatch.setattr(page, "call", held_release)
                one = {
                    "schemaVersion": "1.0",
                    "recordingId": "original-recording",
                    "steps": [
                        {
                            "id": "one",
                            "kind": "click",
                            "target": {"id": "commit", "role": "button"},
                        }
                    ],
                }
                uncertain = replay("same-original-uncertain-operation")
                with pytest.raises(
                    ControlError, match="^browser_replay_write_unconfirmed$"
                ):
                    await uncertain.run(
                        one, {}, before_run=current, before_result=current
                    )
                assert (
                    len(writes) == 2
                    and uncertain.status()["operationId"]
                    == "same-original-uncertain-operation"
                )
                assert uncertain.status()["status"] == "unconfirmed"
                with pytest.raises(
                    ControlError, match="^browser_replay_already_submitted$"
                ):
                    await uncertain.run(
                        one, {}, before_run=current, before_result=current
                    )
                assert len(writes) == 2
                checks.append(
                    "actual one-write/post-return withdrawal retains original operation without replay"
                )
                safe = {
                    "checks": checks,
                    "originalSession": True,
                    "fixtureWebsiteAndFullGrantCallbacks": True,
                    "writes": len(writes),
                    "firstWriteSha256": hashlib.sha256(
                        json.dumps(
                            writes[0], sort_keys=True, ensure_ascii=False
                        ).encode()
                    ).hexdigest(),
                    "actualOwnedFileStore": True,
                    "reportContainsParameterValues": False,
                    "mossworkFactoryNativeAuthorityOrProduction": False,
                }
                (tmp_path / "checked-replay-observation.json").write_text(
                    json.dumps(safe, indent=2) + "\n", encoding="utf-8"
                )
                await session.close()
                session = None
        finally:
            if session:
                await session.close()
            if client:
                await client.close()
            if launched and launched.get("session_id"):
                stopped = await asyncio.to_thread(
                    browser_stop, session_id=launched["session_id"]
                )
                assert stopped.get("stopped") is True
            await runner.cleanup()
