"""Fill a neutral app-creation dialog through real CLI, CDP and extension input."""

import json
from contextlib import asynccontextmanager

from aiohttp import web

from ai_dev_browser.core import (
    click_by_html_id,
    js_evaluate,
    page_goto,
    page_discover,
    page_screenshot,
    page_wait_element,
    type_by_ref,
    type_by_text,
)
from tests.integration.extension_window_support import extension_cli

_HTML = """<!doctype html><meta charset=utf-8><title>Create custom app</title>
<style>body{font:18px sans-serif;margin:32px}input,textarea,button{font:inherit;padding:8px}
.form-row{margin:18px 0}textarea{display:block}#done{color:green}</style>
<h1>Create custom app</h1><form id=app>
<div role=group aria-label="Application details">
<div class=form-row id=nameRow><span>Name</span> <b>*</b> <span>0 / 32</span>
<input id=appName aria-label="0/32"></div>
<div class=form-row><span>Description</span> <b>*</b> <span>0 / 120</span>
<textarea id=description aria-label="0/120"></textarea></div></div>
<button type=button>Name</button>
<label for=owner>Owner</label><input id=owner>
<input id=search placeholder="Search apps">
<div contenteditable=true role=textbox aria-label=Notes id=notes></div>
<button id=submit>Create</button></form><output id=done>Not submitted</output>
<div class=form-row id=ambiguous><span>Account code</span>
<input id=code1><input id=code2></div>
<input id=duplicate1 aria-label="Duplicate label"><input id=duplicate2 aria-label="Duplicate label">
<div class=form-row>Alias * 0/32<input id=alias1></div>
<div class=form-row>Alias * 0/64<input id=alias2></div>
<div id=staticLabel tabindex=0>Static field</div>
<input id=sentinel aria-label=Sentinel value="preserve me">
<iframe title="Contact frame" src=/frame></iframe>
<script>window.events=[];
for(const kind of ['input','beforeinput','keydown','keyup','change'])
 document.addEventListener(kind,e=>events.push({kind,id:e.target.id,trusted:e.isTrusted}),true);
app.onsubmit=async e=>{e.preventDefault();const body={name:appName.value,description:description.value,
 owner:owner.value,search:search.value,notes:notes.textContent,trusted:e.isTrusted};
 const r=await fetch('/receipt',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 if(r.ok)done.textContent='Created '+body.name};</script>"""

_MODAL_HTML = """<!doctype html><meta charset=utf-8><title>Apps with modal field labels</title>
<style>body{font:18px sans-serif;margin:32px}input,textarea,button{font:inherit;padding:8px}
[role=dialog]{position:fixed;inset:100px 12% 40px;background:white;border:2px solid #345;
padding:24px;overflow:auto;box-shadow:0 0 0 9999px #0003}.form-row{margin:20px 0}
input,textarea{display:block}#done{color:green}</style>
<h1>Apps</h1><input id=backgroundSearch placeholder="Search by app name or App ID" value="keep background">
<button id=open>Create Custom App</button><output id=done>Not submitted</output>
<section id=dialog role=dialog aria-modal=true aria-label="Create Custom App" hidden><form id=app>
<h2>Create Custom App</h2><div class=form-row id=nameRow>
<span><strong>Name</strong></span><b>*</b><span>0 / 32</span>
<div><input id=appName aria-label="0/32"></div></div>
<div class=form-row><span>Description</span><b>*</b><span>0 / 120</span>
<textarea id=description aria-label="0/120"></textarea></div>
<div id=extra><div class=form-row><span>Legal <strong>Name</strong></span><b>*</b><span>0 / 64</span>
<input id=legalName aria-label="0/64" value="preserve legal"></div></div>
<button id=submit>Create</button><button type=button id=cancel>Cancel</button>
</form></section><script>
window.events=[];
for(const kind of ['input','beforeinput','keydown','keyup','change'])
 document.addEventListener(kind,e=>events.push({kind,id:e.target.id,trusted:e.isTrusted}),true);
document.querySelector('#open').onclick=()=>dialog.hidden=false;
cancel.onclick=()=>dialog.hidden=true;
app.onsubmit=async e=>{e.preventDefault();const body={name:appName.value,description:description.value,
 background:backgroundSearch.value,trusted:e.isTrusted};
 const r=await fetch('/receipt',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 if(r.ok)done.textContent='Created '+body.name};
const variant=new URLSearchParams(location.search).get('case');
if(variant==='direct')extra.innerHTML='<input id=second aria-label=Name value="preserve duplicate">';
if(variant==='wrapped')extra.innerHTML='<div class=form-row><span>Name</span><b>*</b><span>0 / 64</span><input id=second aria-label="0/64" value="preserve duplicate"></div>';
if(variant==='label')extra.innerHTML='<label for=second>Name</label><input id=second value="preserve duplicate">';
if(variant==='group')nameRow.insertAdjacentHTML('beforeend','<input id=second value="preserve duplicate">');
if(variant==='group-direct'){nameRow.insertAdjacentHTML('beforeend','<input id=second value="preserve duplicate">');extra.innerHTML='<input aria-label=Name value="preserve exact">';}
if(variant==='substring'){nameRow.remove();extra.innerHTML='<input id=second placeholder="Filter by app name" value="preserve duplicate">';}
</script>"""


@asynccontextmanager
async def label_site():
    receipts = []
    app = web.Application()

    async def page(request):
        return web.Response(text=_HTML, content_type="text/html")

    async def frame(request):
        return web.Response(
            text="<label for=email>Contact email</label><input id=email>",
            content_type="text/html",
        )

    async def modal(request):
        return web.Response(text=_MODAL_HTML, content_type="text/html")

    async def receipt(request):
        receipts.append(await request.json())
        return web.json_response({"accepted": True})

    app.router.add_get("/", page)
    app.router.add_get("/frame", frame)
    app.router.add_get("/modal", modal)
    app.router.add_post("/receipt", receipt)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    try:
        yield f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}", receipts
    finally:
        await runner.cleanup()


async def read(driver, expression):
    return (await driver.call(js_evaluate, expression=expression))["result"]


async def modal_journey(driver, folder, caplog):
    """A modal label competes with a real background substring, then duplicates."""
    caplog.set_level("DEBUG", logger="ai_dev_browser.core.ext_bridge")
    evidence = {"refusals": []}
    async with label_site() as (url, receipts):
        try:
            await driver.call(page_goto, url=url + "/modal")
            assert (await driver.call(click_by_html_id, html_id="open"))["clicked"]
            assert await read(driver, "!dialog.hidden")
            hits = await driver.call(
                page_discover,
                text="Name",
                interactable_only=False,
                include_coordinates=False,
            )
            evidence["discovery"] = hits
            assert any(h["name"] == "Search by app name or App ID" for h in hits), hits
            if hasattr(driver, "port"):
                code, result = await extension_cli(
                    driver,
                    "type_by_text",
                    "--name",
                    "Name",
                    "--text",
                    "Moss QA",
                    "--clear",
                )
                assert code == 0, result
            else:
                result = await driver.call(
                    type_by_text, name="Name", text="Moss QA", clear=True
                )
            evidence["name"] = result
            assert (
                result["typed"]
                and result["verified"]
                and result["method"] == "insertText"
            ), result
            field = await driver.call(page_wait_element, selector="#appName")
            assert result["ref"].split("#")[-1] == field["ref"].split("#")[-1]
            description = await driver.call(
                type_by_text,
                name="Description",
                text="Original modal acceptance",
                clear=True,
            )
            assert description["typed"] and description["verified"], description
            evidence["description"] = description
            state = await read(
                driver,
                "({name:appName.value,background:backgroundSearch.value,events})",
            )
            assert (
                state["name"] == "Moss QA" and state["background"] == "keep background"
            ), state
            assert await read(driver, "legalName.value==='preserve legal'")
            assert state["events"] and all(
                e["trusted"] and e["id"] in {"appName", "description"}
                for e in state["events"]
            ), state
            assert receipts == []
            assert (await driver.call(click_by_html_id, html_id="submit"))["clicked"]
            assert (await driver.call(page_wait_element, text="Created Moss QA"))[
                "found"
            ]
            assert receipts == [
                {
                    "name": "Moss QA",
                    "description": "Original modal acceptance",
                    "background": "keep background",
                    "trusted": True,
                }
            ], receipts
            evidence.update(state=state, receipts=list(receipts))
            await driver.call(
                page_screenshot, path=str(folder / "label-typing-accepted.png")
            )
            assert (await driver.call(click_by_html_id, html_id="cancel"))["clicked"]
            assert await read(
                driver, "dialog.hidden && backgroundSearch.value==='keep background'"
            )
            fallback = await driver.call(
                type_by_text,
                name="app name",
                text="unique substring fallback",
                clear=True,
            )
            assert fallback["typed"] and fallback["verified"], fallback
            assert await read(
                driver, "backgroundSearch.value==='unique substring fallback'"
            )
            evidence["substring_fallback"] = fallback
            for variant in (
                "direct",
                "wrapped",
                "label",
                "group",
                "group-direct",
                "substring",
            ):
                await driver.call(page_goto, url=url + "/modal?case=" + variant)
                assert (await driver.call(click_by_html_id, html_id="open"))["clicked"]
                before = await read(
                    driver,
                    "({events:events.slice(),active:document.activeElement.id,values:Array.from(document.querySelectorAll('input,textarea')).map(n=>n.value)})",
                )
                start = len(caplog.records)
                if hasattr(driver, "port"):
                    code, refused = await extension_cli(
                        driver,
                        "type_by_text",
                        "--name",
                        "Name",
                        "--text",
                        "must not land",
                        "--enter",
                        "--timeout",
                        "0",
                    )
                    assert code == 5 and "page_discover" in refused["hint"], refused
                else:
                    refused = await driver.call(
                        type_by_text,
                        name="Name",
                        text="must not land",
                        enter=True,
                        timeout=0,
                    )
                assert (
                    refused["error_code"] == "conflict"
                    and refused["retryable"] is False
                ), refused
                assert (
                    refused["typed"] is False
                    and refused["verified"] is False
                    and refused["input_sent"] is False
                    and refused["methods_tried"] == []
                ), refused
                after = await read(
                    driver,
                    "({events:events.slice(),active:document.activeElement.id,values:Array.from(document.querySelectorAll('input,textarea')).map(n=>n.value)})",
                )
                assert after == before, (variant, before, after)
                sent = [
                    r.args[0]
                    for r in caplog.records[start:]
                    if r.name == "ai_dev_browser.core.ext_bridge"
                    and r.msg == "action: %s%s"
                    and r.args[0].startswith("Input.")
                ]
                assert sent == []
                evidence["refusals"].append(
                    {
                        "case": variant,
                        "result": refused,
                        "state": after,
                        "input_commands": sent,
                    }
                )
                assert len(receipts) == 1
                assert (await driver.call(click_by_html_id, html_id="cancel"))[
                    "clicked"
                ]
                assert await read(
                    driver,
                    "dialog.hidden && backgroundSearch.value==='keep background'",
                )
        finally:
            (folder / "modal-label-evidence.json").write_text(
                json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf8"
            )


async def fill_journey(driver, folder):
    evidence = {"fills": []}
    async with label_site() as (url, receipts):
        try:
            await driver.call(page_goto, url=url)
            if hasattr(driver, "port"):
                code, result = await extension_cli(
                    driver,
                    "type_by_text",
                    "--name",
                    "Name",
                    "--text",
                    "Moss QA",
                    "--clear",
                )
                evidence["cli_exit"] = code
                assert code == 0, result
            else:
                result = await driver.call(
                    type_by_text, name="Name", text="Moss QA", clear=True
                )
            evidence["fills"].append(result)
            assert result["typed"] and result["verified"], result
            assert result["method"] == "insertText" and result["methods_tried"] == [
                "insertText"
            ]
            actual = await driver.call(page_wait_element, selector="#appName")
            assert result["ref"].split("#")[-1] == actual["ref"].split("#")[-1]
            for name, text in (
                ("Description", "QA 验收\nOne trusted submission"),
                ("Owner", "QA owner"),
                ("Search apps", "Moss"),
                ("Notes", "Visible notes"),
                ("Contact email", "qa@example.test"),
            ):
                filled = await driver.call(
                    type_by_text, name=name, text=text, clear=True
                )
                evidence["fills"].append(filled)
                assert filled["typed"] and filled["verified"], filled
            assert (
                await read(
                    driver,
                    "document.querySelector('iframe').contentDocument.querySelector('#email').value",
                )
                == "qa@example.test"
            )
            events = await read(driver, "events")
            assert events and all(
                e["trusted"] for e in events if e["kind"] in {"input", "beforeinput"}
            ), events
            assert {e["id"] for e in events} <= {
                "appName",
                "description",
                "owner",
                "search",
                "notes",
            }
            assert (await driver.call(click_by_html_id, html_id="submit"))["clicked"]
            evidence.update(events=events, receipts=receipts)
            completion = await driver.call(page_wait_element, text="Created Moss QA")
            evidence["completion"] = completion
            assert completion["found"], completion
            assert receipts == [
                {
                    "name": "Moss QA",
                    "description": "QA 验收\nOne trusted submission",
                    "owner": "QA owner",
                    "search": "Moss",
                    "notes": "Visible notes",
                    "trusted": True,
                }
            ], receipts
            rendered = await read(driver, "done.textContent")
            evidence["rendered"] = rendered
            assert rendered == "Created Moss QA", rendered
            await driver.call(
                page_screenshot,
                path=str(folder / "label-typing-accepted.png"),
                full_page=True,
            )
        finally:
            (folder / "label-fill-evidence.json").write_text(
                json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf8"
            )


async def refusal_journey(driver, folder, caplog):
    caplog.set_level("DEBUG", logger="ai_dev_browser.core.ext_bridge")
    evidence = {"refusals": []}
    async with label_site() as (url, receipts):
        try:
            await driver.call(page_goto, url=url)
            await driver.call(js_evaluate, expression="sentinel.focus()")
            start = len(caplog.records)
            for label in ("Account code", "Duplicate label", "Alias", "Static field"):
                if hasattr(driver, "port"):
                    code, result = await extension_cli(
                        driver,
                        "type_by_text",
                        "--name",
                        label,
                        "--text",
                        "must not land",
                        "--enter",
                        "--timeout",
                        "0",
                    )
                    assert code in {2, 5}, result
                    assert "page_discover" in result["hint"] and not result["retryable"]
                else:
                    result = await driver.call(
                        type_by_text,
                        name=label,
                        text="must not land",
                        enter=True,
                        timeout=0,
                    )
                evidence["refusals"].append(result)
                assert result["typed"] is False and result["verified"] is False, result
                assert (
                    result["methods_tried"] == [] and result["input_sent"] is False
                ), result
                assert not result.get("entered") and result["error_code"] in {
                    "validation",
                    "conflict",
                }
            wrapper = await driver.call(page_wait_element, selector="#nameRow")
            original_text = await read(driver, "nameRow.textContent")
            if hasattr(driver, "port"):
                code, refused_ref = await extension_cli(
                    driver,
                    "type_by_ref",
                    "--ref",
                    wrapper["ref"],
                    "--text",
                    original_text,
                    "--enter",
                )
                evidence["refusals"].append(refused_ref)
                assert code == 2 and not refused_ref["input_sent"]
                assert "page_discover" in refused_ref["hint"]
            result = await driver.call(
                type_by_ref, ref=wrapper["ref"], text=original_text, enter=True
            )
            evidence["refusals"].append(result)
            assert result["typed"] is False and result["verified"] is False, result
            assert result["methods_tried"] == [] and result["input_sent"] is False
            dispatched = [
                r.args[0]
                for r in caplog.records[start:]
                if r.name == "ai_dev_browser.core.ext_bridge"
                and r.msg == "action: %s%s"
                and r.args[0].startswith("Input.")
            ]
            state = await read(
                driver,
                "({events,active:document.activeElement.id,sentinel:sentinel.value,values:[appName.value,code1.value,code2.value,duplicate1.value,duplicate2.value],wrapperValue:Object.hasOwn(nameRow,'value')})",
            )
            evidence.update(state=state, input_commands=dispatched, receipts=receipts)
            assert state == {
                "events": [],
                "active": "sentinel",
                "sentinel": "preserve me",
                "values": ["", "", "", "", ""],
                "wrapperValue": False,
            }, state
            assert dispatched == [] and receipts == []
        finally:
            (folder / "label-refusal-evidence.json").write_text(
                json.dumps(evidence, indent=2), encoding="utf8"
            )
