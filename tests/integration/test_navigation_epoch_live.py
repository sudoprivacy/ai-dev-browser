"""Real address-bar UI keeps its old-frame fence across same-tab navigation.

The owned host uses fixture grants; Product/native authority is not supplied.
"""

import asyncio
import base64
import contextlib
from importlib.resources import files
import json

import aiohttp
from aiohttp import web
import pytest

from ai_dev_browser.core import human
from ai_dev_browser.core.connection import BrowserClient
from ai_dev_browser.core.elements import click_by_html_id, type_by_text
from ai_dev_browser.core.page import js_evaluate, page_screenshot
from ai_dev_browser.remote.control import ControlError
from ai_dev_browser.remote.session import BrowserSession
from tests.integration.test_remote_view import wait_for
from tests.integration.test_session_operations_live import (
    owned_operations_browser as owned_operations_browser,
)

# A separate fixture name creates the independent UI browser from the same factory.
navigation_viewer_browser = owned_operations_browser


VIEWER = """<!doctype html><meta charset=utf-8><title>Navigation epoch viewer</title>
<style>body{font:16px sans-serif;margin:16px}input{width:440px}button{margin:4px}
#screen{display:block;width:640px;max-width:none;border:1px solid #999}</style>
<label>Address<input id=address></label><button id=go>Go</button>
<button id=back>Back</button><button id=forward>Forward</button><button id=reload>Reload</button>
<p id=status>Connecting</p><img id=screen tabindex=0>
<label>Insert text<input id=entry></label><button id=insert>Insert</button>
<script type=module>
import {PageSurface} from '/page-view.js';
window.pending=true;window.errors=[];window.operations=[];window.frames=[];
const image=document.querySelector('#screen');
let queue=Promise.resolve();
const surface=new PageSurface(image,input=>queue=queue.then(()=>act({kind:'input',input})));
function busy(value){window.pending=value;for(const b of document.querySelectorAll('button'))b.disabled=value;}
async function capture(minimum){
  const deadline=performance.now()+15000;
  while(performance.now()<deadline){
    const response=await fetch('/frame?epoch='+state.controlEpoch+'&target='+state.targetEpoch);
    const frame=await response.json();
    if(!response.ok)throw Error(frame.error);
    if(frame.targetEpoch>=minimum){
      surface.frame(frame);await image.decode();window.frames.push({targetEpoch:frame.targetEpoch});
      document.querySelector('#status').textContent='Ready version '+frame.targetEpoch;
      busy(false);return;
    }
    await new Promise(resolve=>setTimeout(resolve,25));
  }
  throw Error('Original fresh-frame fence did not advance');
}
async function act(action){
  if(window.pending)throw Error('Input is waiting for a fresh frame');
  busy(true);
  const original=state.targetEpoch;
  try{
    const response=await fetch('/action',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({...action,controlEpoch:state.controlEpoch,targetEpoch:original})});
    const body=await response.json();if(!response.ok)throw Error(body.error);
    window.state=body.session;window.operations.push({kind:action.kind,result:body.result,state:body.session});
    const navigation=['navigate','back','forward','reload'].includes(action.kind);
    const minimum=navigation&&body.result?.navigationRequested!==false?original+1:original;
    await capture(minimum);
  }catch(error){window.errors.push(String(error));throw error;}
}
document.querySelector('#go').onclick=()=>act({kind:'navigate',url:document.querySelector('#address').value});
for(const kind of ['back','forward','reload'])document.querySelector('#'+kind).onclick=()=>act({kind});
document.querySelector('#insert').onclick=()=>act({kind:'input',input:{kind:'text',text:document.querySelector('#entry').value}});
window.state=await(await fetch('/state')).json();await capture(state.targetEpoch);
</script>"""


async def navigation_journey(browser, viewer_browser, tmp_path):
    session = None
    ui = None
    receipts, commands, frames = [], [], []
    slow_entered, slow_release = asyncio.Event(), asyncio.Event()
    reload_entered, reload_release, reload_ack = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )
    hold_reload = False
    document_requests = {}
    grant = True
    pending_tasks = []

    async def current():
        if not grant:
            raise PermissionError("Original fixture grant withdrawn")

    async def document(request):
        name = request.match_info["name"]
        document_requests[name] = document_requests.get(name, 0) + 1
        generation = document_requests[name]
        if name == "b" and hold_reload:
            reload_entered.set()
            await reload_release.wait()
        if name.startswith("slow"):
            slow_entered.set()
            await slow_release.wait()
        return web.Response(
            text=f"""<!doctype html><meta charset=utf-8><title>Document {name}</title>
<style>body{{margin:24px;font:20px sans-serif}}input,button{{display:block;width:300px;height:44px;margin:18px 0}}</style>
<h1>Document {name}</h1><label>Request<input id=note></label><button id=commit>Commit once</button><pre id=result></pre>
<script>window.documentGeneration={generation};window.inputTrust=[];note.oninput=e=>inputTrust.push(e.isTrusted);
commit.onclick=async e=>{{const r=await fetch('/receipt',{{method:'POST',headers:{{'Content-Type':'application/json'}},
body:JSON.stringify({{document:{json.dumps(name)},value:note.value,trusted:e.isTrusted,inputTrust}})}});
result.textContent=JSON.stringify(await r.json());}};</script>""",
            content_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    async def receipt(request):
        value = await request.json()
        receipts.append(value)
        return web.json_response({"sequence": len(receipts)})

    async def state_handler(request):
        return web.json_response(await session.state(before_effect=current))

    async def frame_handler(request):
        frame = await session.frame(
            "original-viewer",
            int(request.query["epoch"]),
            int(request.query["target"]),
            before_effect=current,
        )
        frames.append({key: frame[key] for key in ("controlEpoch", "targetEpoch")})
        return web.json_response(frame)

    async def action_handler(request):
        body = await request.json()
        try:
            result = await session.action(
                "original-human",
                body["controlEpoch"],
                body["targetEpoch"],
                body,
                before_effect=current,
            )
            return web.json_response(
                {
                    "result": result,
                    "session": await session.state(before_effect=current),
                }
            )
        except ControlError as error:
            return web.json_response({"error": error.code}, status=409)

    app = web.Application()
    app.router.add_get("/document/{name}", document)
    app.router.add_post("/receipt", receipt)

    async def viewer(_request):
        return web.Response(text=VIEWER, content_type="text/html")

    async def asset(_request):
        return web.Response(
            text=files("ai_dev_browser.remote").joinpath("page_view.js").read_text(),
            content_type="text/javascript",
        )

    app.router.add_get("/viewer", viewer)
    app.router.add_get("/page-view.js", asset)
    app.router.add_get("/state", state_handler)
    app.router.add_get("/frame", frame_handler)
    app.router.add_post("/action", action_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    server = web.TCPSite(runner, "127.0.0.1", 0)
    await server.start()
    origin = f"http://127.0.0.1:{server._server.sockets[0].getsockname()[1]}"
    try:
        async with aiohttp.ClientSession() as http:
            session = BrowserSession(browser, http)
            await session.state(before_effect=current)
            await session.control.take("original-human", before_effect=current)
            await session.attach("original-viewer", before_effect=current)
            page = await session._connect_page()
            original = session.target_id, page, session.control.epoch
            original_call = page.call

            async def counted(method, params=None, timeout=20):
                if method in (
                    "Page.navigate",
                    "Page.reload",
                    "Page.navigateToHistoryEntry",
                ):
                    commands.append({"method": method, "params": params})
                response = await original_call(method, params, timeout=timeout)
                if method == "Page.reload" and hold_reload:
                    reload_ack.set()
                return response

            page.call = counted
            # Like the consuming host, run its web UI in a separate browser.
            # Remote Page.bringToFront must not hide this test driver's tab.
            ui = await viewer_browser.get(origin + "/viewer")

            async def ui_read(expression):
                return (await js_evaluate(ui, expression))["result"]

            async def ready():
                return await ui_read("window.pending===false")

            async def click(html_id):
                result = await click_by_html_id(ui, html_id)
                assert result["clicked"], result
                await wait_for(ready, bool)

            async def navigate(name, *, title=None):
                before = session.control.target_epoch
                result = await type_by_text(
                    ui,
                    "Address",
                    origin + "/document/" + name,
                    clear=True,
                    human_like=False,
                )
                assert result["typed"] and result["verified"], result
                await click("go")
                assert session.control.target_epoch == before + 1
                assert await page.js("document.title") == "Document " + (title or name)

            await wait_for(ready, bool)
            await navigate("a")
            old = session.control.target_epoch
            with pytest.raises(ControlError, match="^stale_browser_operation$"):
                await session.frame("original-viewer", session.control.epoch, old - 1)

            async def native_click_target(selector):
                point = await page.js(
                    f"(()=>{{const r=document.querySelector({json.dumps(selector)}).getBoundingClientRect();return {{x:r.x+r.width/2,y:r.y+r.height/2}}}})()"
                )
                box = await ui_read(
                    "(()=>{const r=document.querySelector('#screen').getBoundingClientRect();return {x:r.x,y:r.y,width:r.width}})()"
                )
                scale = box["width"] / session._size[0]
                await human.mouse_click(
                    ui, box["x"] + point["x"] * scale, box["y"] + point["y"] * scale
                )
                await wait_for(ready, bool)

            await native_click_target("#note")
            await wait_for(
                lambda: page.js("document.activeElement.id"),
                lambda name: name == "note",
            )
            result = await type_by_text(
                ui, "Insert text", "\u4e2d\u6587 epoch", human_like=False
            )
            assert result["typed"] and result["verified"]
            await click("insert")
            await wait_for(
                lambda: page.js("note.value"),
                lambda value: value == "\u4e2d\u6587 epoch",
            )
            await native_click_target("#commit")
            await wait_for(
                lambda: asyncio.sleep(0, result=len(receipts)), lambda count: count == 1
            )
            assert receipts == [
                {
                    "document": "a",
                    "value": "\u4e2d\u6587 epoch",
                    "trusted": True,
                    "inputTrust": [True],
                }
            ]
            await navigate("b")
            for kind, expected in (("back", "a"), ("forward", "b"), ("reload", "b")):
                before = session.control.target_epoch
                await click(kind)
                assert session.control.target_epoch == before + 1
                await wait_for(
                    lambda: page.js("document.title"),
                    lambda title: title == "Document " + expected,
                )
            # Same-document history commits without changing the loader.
            await navigate("b#review", title="b")
            for kind, expected_hash in (("back", ""), ("forward", "#review")):
                before = session.control.target_epoch
                await click(kind)
                assert session.control.target_epoch == before + 1
                assert await page.js("location.hash") == expected_hash
            before, count = session.control.target_epoch, len(commands)
            await click("forward")
            assert session.control.target_epoch == before and len(commands) == count
            assert (await ui_read("window.operations.at(-1).result")) == {
                "navigationRequested": False,
                "targetEpoch": before,
            }
            assert await ui_read("window.errors") == []
            screenshot = await page_screenshot(
                ui, path=str(tmp_path / "actual-navigation-viewer.png")
            )
            assert screenshot["size"] > 1000 and screenshot["width"] > 640, screenshot

            # Reload's CDP ACK precedes the actual document. Its input barrier
            # must remain held, so old pixels cannot acquire the next version.
            before = session.control.target_epoch
            hold_reload = True
            reloading = asyncio.create_task(
                session.action(
                    "original-human",
                    session.control.epoch,
                    before,
                    {"kind": "reload"},
                    before_effect=current,
                )
            )
            pending_tasks.append(reloading)
            await asyncio.wait_for(reload_entered.wait(), 10)
            await asyncio.wait_for(reload_ack.wait(), 5)
            assert not reloading.done() and session.control._operations.locked()
            assert session.control.target_epoch == before
            reload_release.set()
            await reloading
            hold_reload = False
            assert session.control.target_epoch == before + 1
            assert await page.js("window.documentGeneration") == document_requests["b"]

            # The real network response holds the original navigation under its
            # input lock. Canceling the caller must drain that one send.
            before = session.control.target_epoch
            navigation = asyncio.create_task(
                session.action(
                    "original-human",
                    session.control.epoch,
                    before,
                    {"kind": "navigate", "url": origin + "/document/slow-cancel"},
                    before_effect=current,
                )
            )
            pending_tasks.append(navigation)
            await asyncio.wait_for(slow_entered.wait(), 10)
            effects = []

            async def old_input(commands):
                effects.append("old-page-input")
                await commands.call("Input.insertText", {"text": "MUST_NOT_BE_SENT"})

            queued = asyncio.create_task(
                session.page_operation(
                    "old-viewer",
                    "original-human",
                    session.control.epoch,
                    before,
                    old_input,
                    before_effect=current,
                )
            )
            pending_tasks.append(queued)
            await asyncio.sleep(0)
            assert not queued.done()
            navigation.cancel()
            await asyncio.sleep(0)
            assert not navigation.done() and session.control._operations.locked()
            slow_release.set()
            with pytest.raises(asyncio.CancelledError):
                await navigation
            with pytest.raises(ControlError, match="^stale_browser_operation$"):
                await queued
            assert effects == [] and session.control.target_epoch == before + 1
            assert (
                len(
                    [
                        value
                        for value in commands
                        if value["params"].get("url", "").endswith("/slow-cancel")
                    ]
                )
                == 1
            )

            # Lose only the response after Chrome actually committed. The SDK
            # must invalidate the previous version and never send a replacement.
            async def lose_ack(method, params=None, timeout=20):
                response = await counted(method, params, timeout)
                if method == "Page.navigate":
                    await page.wait_navigation(response)
                    raise TimeoutError("Original navigation result lost")
                return response

            page.call = lose_ack
            before, count = session.control.target_epoch, len(commands)
            with pytest.raises(TimeoutError, match="Original navigation result lost"):
                await session.action(
                    "original-human",
                    session.control.epoch,
                    before,
                    {"kind": "navigate", "url": origin + "/document/lost-ack"},
                    before_effect=current,
                )
            page.call = counted
            assert (
                len(commands) == count + 1
                and session.control.target_epoch == before + 1
            )
            assert await page.js("document.title") == "Document lost-ack"
            with pytest.raises(ControlError, match="^stale_browser_operation$"):
                await session.page_operation(
                    "old-viewer",
                    "original-human",
                    session.control.epoch,
                    before,
                    old_input,
                    before_effect=current,
                )

            async def withdraw_history(method, params=None, timeout=20):
                nonlocal grant
                response = await counted(method, params, timeout)
                if method == "Page.getNavigationHistory":
                    grant = False
                return response

            page.call = withdraw_history
            before, count = session.control.target_epoch, len(commands)
            with pytest.raises(ControlError, match="^browser_authorization_denied$"):
                await session.action(
                    "original-human",
                    session.control.epoch,
                    before,
                    {"kind": "back"},
                    before_effect=current,
                )
            page.call = counted
            grant = True
            assert len(commands) == count and session.control.target_epoch == before
            assert await page.js("document.title") == "Document lost-ack"
            fresh = await session.frame(
                "original-viewer", session.control.epoch, before, before_effect=current
            )
            assert fresh["targetEpoch"] == before
            (tmp_path / "final-navigation-frame.jpg").write_bytes(
                base64.b64decode(fresh["data"])
            )
            assert (session.target_id, session._page, session.control.epoch) == original
            assert session.control.state == "human" and len(receipts) == 1
            (tmp_path / "navigation-epoch.json").write_text(
                json.dumps(
                    {
                        "transport": getattr(browser, "transport", None) or "cdp",
                        "sameOriginalTargetPageAndHumanLease": True,
                        "actualUIOperations": await ui_read("window.operations"),
                        "actualFrames": frames,
                        "actualNativeNavigationCommands": commands,
                        "trustedNativeCommits": receipts,
                        "cancellationDrained": True,
                        "oldInputCallbackNotInvoked": True,
                        "lostAckNotResent": True,
                        "withdrawalAfterHistorySentNoNavigation": True,
                        "hostGrantsAreFixtures": True,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
    except BaseException:
        if ui:
            with contextlib.suppress(Exception):
                observed = await js_evaluate(
                    ui,
                    "({pending:window.pending,state:window.state,errors:window.errors,operations:window.operations})",
                )
                (tmp_path / "failed-ui-observation.json").write_text(
                    json.dumps(observed, indent=2), encoding="utf-8"
                )
                await page_screenshot(ui, path=str(tmp_path / "failed-ui.png"))
        raise
    finally:
        slow_release.set()
        reload_release.set()
        grant = True
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)
        if session:
            await session.close()
        if ui:
            await ui.close()
        await runner.cleanup()


async def test_real_address_bar_fresh_frame_native_input_and_navigation_races(
    owned_operations_browser, navigation_viewer_browser, tmp_path
):
    await navigation_journey(
        owned_operations_browser, navigation_viewer_browser, tmp_path
    )


async def test_extension_address_bar_fresh_frame_native_input_and_navigation_races(
    live_extension, navigation_viewer_browser, tmp_path
):
    browser = await BrowserClient.connect(
        "127.0.0.1",
        live_extension.port,
        ws_url=f"ws://127.0.0.1:{live_extension.port}/devtools/browser",
    )
    browser.transport = "extension"
    browser._automation_target_id = str(
        live_extension.bridge.identity["automation_target_id"]
    )
    try:
        await navigation_journey(browser, navigation_viewer_browser, tmp_path)
    finally:
        await browser.close()
