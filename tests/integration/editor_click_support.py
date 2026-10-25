"""Real Monaco documents and collapsed navigation; never use a user's app."""

import asyncio
from contextlib import asynccontextmanager
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import time
from urllib.request import urlopen

from aiohttp import web

from ai_dev_browser.core import (
    click_by_ref,
    click_by_text,
    click_by_html_id,
    click_by_xpath,
    js_evaluate,
    page_discover,
    page_goto,
    page_screenshot,
    type_by_ref,
    type_by_text,
)

MONACO_VERSION = "0.55.1"
MONACO_INTEGRITY = "jz4x+TJNFHwHtwuV9vA9rMujcZRb0CEilTEwG2rRSpe/A7Jdkuj8xPKttCgOh+v/lkHy7HsZ64oj+q3xoAFl9A=="  # pragma: allowlist secret -- public npm SHA-512


def install_monaco(folder):
    """Use the unchanged official npm distribution, pinned by SHA-512."""
    cache = Path(
        os.environ.get(
            "AI_DEV_BROWSER_TEST_MONACO_TARBALL",
            str(
                Path(tempfile.gettempdir())
                / "adb-test-fixtures"
                / f"monaco-editor-{MONACO_VERSION}.tgz"
            ),
        )
    )
    if cache.is_file():
        content = cache.read_bytes()
    else:
        for attempt in range(3):
            try:
                with urlopen(
                    f"https://registry.npmjs.org/monaco-editor/-/monaco-editor-{MONACO_VERSION}.tgz",
                    timeout=45,
                ) as response:
                    content = response.read()
                break
            except OSError:
                if attempt == 2:
                    raise
                time.sleep(0.5)
    assert (
        base64.b64encode(hashlib.sha512(content).digest()).decode() == MONACO_INTEGRITY
    )
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=cache.parent, delete=False) as temporary:
            temporary.write(content)
            temporary_name = temporary.name
        os.replace(temporary_name, cache)
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
        for member in archive:
            if not member.isfile() or not member.name.startswith("package/min/vs/"):
                continue
            path = folder / member.name.removeprefix("package/min/")
            assert path.resolve().is_relative_to(folder.resolve())
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.extractfile(member).read())
    assert (folder / "vs/loader.js").is_file()
    return folder


_EDITOR = """<!doctype html><meta charset="utf-8"><title>Neutral JSON editor</title>
<style>body{font:16px sans-serif} .editor{width:900px;height:300px;border:1px solid #444}</style>
<h1>Batch scope JSON</h1><div id="editor" class="editor"></div>
<h2>Independent editor</h2><div id="other" class="editor"></div>
<label>Ordinary field<input id="ordinary" aria-label="Ordinary field"></label>
<label>Ordinary textarea<textarea id="notes" aria-label="Ordinary textarea"></textarea></label>
<script src="/vs/loader.js"></script><script>
require.config({paths:{vs:'/vs'}});
require(['vs/editor/editor.main'],()=>{
  window.editorChanges=[]; window.trustedInputs=[];
  document.addEventListener('input',e=>trustedInputs.push(e.isTrusted),true);
  window.initialDocument=JSON.stringify({originalExample:Array.from({length:400},(_,i)=>'original-'+i)},null,2);
  window.realEditor=monaco.editor.create(document.querySelector('#editor'),{
    value:initialDocument,language:'json',automaticLayout:true,
    autoIndent:'full',autoClosingBrackets:'always',formatOnType:true,
    ariaLabel:'Editor content;Press Alt+F1 for Accessibility Options.'});
  window.otherEditor=monaco.editor.create(document.querySelector('#other'),{
    value:'independent document',language:'plaintext',automaticLayout:true});
  realEditor.onDidChangeModelContent(e=>editorChanges.push({version:e.versionId,changes:e.changes.length}));
  if(new URLSearchParams(location.search).has('rejectEdit')){
    realEditor.onDidChangeModelContent(()=>{
      if(realEditor.getValue()!==initialDocument)realEditor.getModel().setValue(initialDocument);
    });
  }
  if(new URLSearchParams(location.search).has('privateApi')){
    window.monaco=undefined; window.require=undefined;
  }
  window.editorReady=true;
});
</script>"""

_NAV = """<!doctype html><meta charset="utf-8"><title>Neutral admin navigation</title>
<style>body{font:18px sans-serif}button,a{display:block;height:42px;width:240px}
#submenu{height:0;overflow:hidden}#submenu.open{height:60px}
#focusSink{height:50px;width:260px;background:#eee}
#coverBox{position:relative;width:240px;height:45px}#coverBox>*{position:absolute;inset:0}
#overlay{z-index:2;background:#bbb}</style>
<h1>Organization overview</h1>
<button id="toggle" aria-expanded="false">Workplace</button>
<div id="submenu"><a id="review" href="#audit">App Review 15</a></div>
<div id="focusSink" tabindex="0">Overview summary</div>
<div id="coverBox"><button id="covered">Covered action</button><div id="overlay">Modal overlay</div></div>
<button id="plain">Visible action</button><output id="result">No action</output>
<script>window.events=[];window.activated=[];
document.addEventListener('click',e=>events.push({id:e.target.id,trusted:e.isTrusted}),true);
toggle.onclick=()=>{submenu.classList.toggle('open');toggle.setAttribute('aria-expanded',submenu.classList.contains('open'))};
review.onclick=e=>activated.push({id:'review',trusted:e.isTrusted});
covered.onclick=e=>{activated.push({id:'covered',trusted:e.isTrusted});result.textContent='Covered action fired'};
plain.onclick=e=>{activated.push({id:'plain',trusted:e.isTrusted});result.textContent='Visible action fired'};
</script>"""

_NESTED = """<!doctype html><meta charset="utf-8"><title>Nested controls</title>
<iframe id="frame" src="/frame" style="width:900px;height:200px;border:4px solid #555;transform:scale(.9);transform-origin:top left"></iframe>
<div id="openHost"></div><div id="closedHost"></div>
<script>window.actions=[];
for(const mode of ['open','closed']){
 const root=document.querySelector('#'+mode+'Host').attachShadow({mode});
 root.innerHTML='<button style="width:260px;height:50px">'+mode+' shadow action</button>';
 root.querySelector('button').onclick=e=>actions.push({id:mode,trusted:e.isTrusted});
}</script>"""

_FRAME = """<!doctype html><meta charset="utf-8"><style>button{margin:18px;width:260px;height:50px}</style>
<button id="nestedAction">Nested frame action</button><script>
window.actions=[];nestedAction.onclick=e=>actions.push({id:'frame',trusted:e.isTrusted});
</script>"""


@asynccontextmanager
async def interaction_site(assets):
    app = web.Application()

    async def editor_page(request):
        return web.Response(text=_EDITOR, content_type="text/html")

    async def navigation_page(request):
        return web.Response(text=_NAV, content_type="text/html")

    async def nested_page(request):
        return web.Response(
            text=_FRAME if request.path == "/frame" else _NESTED,
            content_type="text/html",
        )

    app.router.add_get("/editor", editor_page)
    app.router.add_get("/nav", navigation_page)
    app.router.add_get("/nested", nested_page)
    app.router.add_get("/frame", nested_page)
    app.router.add_static("/vs", assets / "vs")
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    try:
        yield f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    finally:
        await runner.cleanup()


async def read(driver, expression):
    return (await driver.call(js_evaluate, expression=expression))["result"]


async def ready(driver):
    deadline = asyncio.get_running_loop().time() + 20
    while not await read(driver, "window.editorReady === true"):
        assert asyncio.get_running_loop().time() < deadline, (
            "Actual Monaco did not finish loading"
        )
        await asyncio.sleep(0.05)


async def editor_journey(driver, url, folder, private_api=False):
    journal = {"monaco": MONACO_VERSION, "private_api": private_api}
    try:
        await driver.call(
            page_goto, url=url + "/editor" + ("?privateApi=1" if private_api else "")
        )
        await ready(driver)
        found = await driver.call(
            page_discover,
            text="Editor content",
            include_coordinates=False,
            dom_scan=False,
        )
        found = [item for item in found if "Press Alt+F1" in item.get("name", "")]
        assert len(found) == 1, found
        ref = found[0]["ref"]
        before = await read(
            driver,
            "({model:realEditor.getValue(),proxy:document.querySelector('#editor textarea').value,version:realEditor.getModel().getVersionId()})",
        )
        journal["before"] = before
        scopes = {
            "scopes": {
                "tenant": [
                    "im:message:send_as_bot",
                    "im:message.group_at_msg:readonly",
                    "im:message.p2p_msg:readonly",
                    "im:resource",
                    "im:chat.members:read",
                    "contact:user.employee_id:readonly",
                    "application:application:self_manage",
                ],
                "user": [],
            }
        }
        short = json.dumps(scopes, indent=2)
        texts = [
            short,
            json.dumps(
                {**scopes, "longDocument": [f"row-{i}" for i in range(600)]}, indent=2
            ),
        ]
        journal["fills"] = []
        for text in texts:
            if hasattr(driver, "port") and not journal["fills"]:
                from .extension_window_support import extension_cli

                flags = ["--ref", ref, "--text", text, "--clear"]
                if private_api:
                    flags.append("--enter")
                status, result = await extension_cli(driver, "type_by_ref", *flags)
                assert (status != 0) if private_api else (status == 0), result
                journal["actual_cli_used"] = True
            else:
                result = await driver.call(
                    type_by_ref, ref=ref, text=text, clear=True, enter=private_api
                )
            observed = await read(
                driver,
                "({model:realEditor.getValue(),proxy:document.querySelector('#editor textarea').value,other:otherEditor.getValue(),changes:editorChanges,trusted:trustedInputs})",
            )
            journal["fills"].append(
                {"result": result, "observed": observed, "requested": text}
            )
            if private_api:
                assert result["typed"] is False and result["verified"] is False, result
                assert (
                    result["error_code"] == "unsupported"
                    and result["input_sent"] is False
                ), result
                assert not result.get("entered"), result
                assert (
                    observed["model"] == before["model"] and observed["changes"] == []
                )
                break
            assert result["typed"] and result["verified"], result
            assert result["methods_tried"] == ["editor"], result
            assert observed["model"] == text, (
                "Full Monaco model must match exactly once"
            )
            assert len(observed["changes"]) == len(journal["fills"]), (
                "Each replacement must produce only one model edit"
            )
            assert observed["other"] == "independent document"
            assert json.loads(observed["model"]) == json.loads(text)
        if not private_api:
            for name, value in (
                ("Ordinary field", "ordinary input"),
                ("Ordinary textarea", "first line\nsecond line"),
            ):
                result = await driver.call(
                    type_by_text, name=name, text=value, clear=True
                )
                assert result["typed"] and result["verified"], result
            assert (
                await read(driver, "document.querySelector('#ordinary').value")
                == "ordinary input"
            )
            assert (
                await read(driver, "document.querySelector('#notes').value")
                == "first line\nsecond line"
            )
        await driver.call(
            js_evaluate, expression="window.scrollTo(0,0);realEditor.revealLine(1);true"
        )
        await driver.call(
            page_screenshot, path=str(folder / "editor-accepted.png"), full_page=True
        )
    finally:
        (folder / "editor-evidence.json").write_text(
            json.dumps(journal, indent=2), encoding="utf-8"
        )


async def navigation_journey(driver, url, folder):
    journal = {}
    try:
        await driver.call(page_goto, url=url + "/nav")
        hidden = await driver.call(page_discover, text="App Review 15", dom_scan=False)
        assert len(hidden) == 1, hidden
        journal["discovered"] = hidden
        first = await driver.call(click_by_ref, ref=hidden[0]["ref"])
        journal["hidden_ref"] = first
        journal["hidden_events"] = await read(driver, "events")
        assert first["clicked"] is False and first["verified"] is False, first
        assert first["input_sent"] is False and not first["retryable"], first
        assert hidden[0]["visible"] is False and hidden[0]["actionable"] is False, (
            hidden
        )
        second = await driver.call(click_by_text, text="App Review 15")
        journal["hidden_text"] = second
        assert not second["clicked"] and not second["verified"], second
        if hasattr(driver, "port"):
            from .extension_window_support import extension_cli

            status, cli_refusal = await extension_cli(
                driver, "click_by_text", "--text", "App Review 15"
            )
            journal["cli_hidden_text"] = cli_refusal
            assert (
                status != 0
                and not cli_refusal["clicked"]
                and not cli_refusal["input_sent"]
            ), cli_refusal
            assert cli_refusal["error_code"] == "conflict" and "hint" in cli_refusal, (
                cli_refusal
            )
        assert await read(driver, "events") == [], (
            "Hidden links must not dispatch onto adjacent controls"
        )
        for function, locator in (
            (click_by_html_id, {"html_id": "review"}),
            (click_by_xpath, {"xpath": "//a[@id='review']"}),
        ):
            refusal = await driver.call(function, **locator)
            assert (
                not refusal["clicked"]
                and not refusal["verified"]
                and not refusal["input_sent"]
            ), refusal
        assert await read(driver, "events") == [], (
            "Changing locator must not bypass hit-target refusal"
        )
        covered = await driver.call(click_by_text, text="Covered action")
        journal["covered"] = covered
        assert not covered["clicked"] and not covered["verified"], covered
        assert await read(driver, "events") == [], (
            "A blocked hit target must not get synthetic fallback"
        )
        opened = await driver.call(click_by_text, text="Workplace")
        assert opened["clicked"] and opened["verified"], opened
        visible = await driver.call(page_discover, text="App Review 15", dom_scan=False)
        assert visible[0]["visible"] and visible[0]["actionable"], visible
        activated = await driver.call(click_by_text, text="App Review 15")
        journal["activated"] = activated
        assert (
            activated["clicked"] and activated["verified"] and activated["navigated"]
        ), activated
        assert await read(driver, "window.activated") == [
            {"id": "review", "trusted": True}
        ]
        plain = await driver.call(click_by_text, text="Visible action")
        assert plain["clicked"] and plain["verified"] and not plain["navigated"], plain
        journal["final"] = await read(
            driver, "({events,activated,url:location.hash,result:result.textContent})"
        )
        assert journal["final"]["activated"] == [
            {"id": "review", "trusted": True},
            {"id": "plain", "trusted": True},
        ]
        await driver.call(page_screenshot, path=str(folder / "navigation-accepted.png"))
    finally:
        (folder / "navigation-evidence.json").write_text(
            json.dumps(journal, indent=2), encoding="utf-8"
        )


async def rejected_editor_journey(driver, url, folder):
    journal = {}
    try:
        await driver.call(page_goto, url=url + "/editor?rejectEdit=1")
        await ready(driver)
        found = await driver.call(
            page_discover,
            text="Editor content;Press Alt+F1",
            dom_scan=False,
            include_coordinates=False,
        )
        assert len(found) == 1, found
        filled = await driver.call(
            type_by_ref,
            ref=found[0]["ref"],
            text='{"scopes":{"tenant":[],"user":[]}}',
            clear=True,
            enter=True,
        )
        observed = await read(
            driver,
            "({unchanged:realEditor.getValue()===initialDocument,changes:editorChanges.length,other:otherEditor.getValue()})",
        )
        journal.update(result=filled, observed=observed)
        assert filled["verified"] is False and filled["error_code"] == "conflict", (
            filled
        )
        assert filled["retryable"] is False and not filled.get("entered"), filled
        assert filled["methods_tried"] == ["editor"], filled
        assert observed == {
            "unchanged": True,
            "changes": 2,
            "other": "independent document",
        }, observed
    finally:
        (folder / "rejected-editor-evidence.json").write_text(
            json.dumps(journal, indent=2), encoding="utf-8"
        )


async def nested_click_journey(driver, url, folder):
    journal = []
    try:
        await driver.call(page_goto, url=url + "/nested")
        for name in (
            "Nested frame action",
            "open shadow action",
            "closed shadow action",
        ):
            found = await driver.call(page_discover, text=name, dom_scan=False)
            assert found and found[0]["visible"] and found[0]["actionable"], found
            clicked = await driver.call(click_by_ref, ref=found[0]["ref"])
            journal.append({"name": name, "discovered": found, "clicked": clicked})
            assert clicked["clicked"] and clicked["verified"], clicked
        await driver.call(click_by_html_id, html_id="nestedAction")
        assert await read(
            driver, "document.querySelector('#frame').contentWindow.actions"
        ) == [{"id": "frame", "trusted": True}, {"id": "frame", "trusted": True}]
        assert await read(driver, "actions") == [
            {"id": "open", "trusted": True},
            {"id": "closed", "trusted": True},
        ]
        await driver.call(
            page_screenshot, path=str(folder / "nested-click-accepted.png")
        )
    finally:
        (folder / "nested-click-evidence.json").write_text(
            json.dumps(journal, indent=2), encoding="utf-8"
        )
