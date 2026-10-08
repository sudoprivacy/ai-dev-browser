"""mouse_drag holds the button through the move; mouse_move doesn't sweep (E2E).

Two bugs in Tab's low-level input:
- mouse_drag's intermediate mouseMoved carried no `buttons`, so the browser saw
  buttons=0 during the drag — a page reading e.buttons never saw a drag, and
  setPointerCapture() in a pointermove threw NotFoundError (pointer not active).
- mouse_move interpolated from a hardcoded (0,0), sweeping the cursor across the
  whole page every move and tripping hover/tooltip handlers en route.
Launches a real headless Chrome.
"""

from __future__ import annotations

import base64
import contextlib

import pytest

from ai_dev_browser.core import connect_browser, get_active_tab
from ai_dev_browser.core.browser import browser_start, browser_stop

_PAGE = """<!doctype html><meta charset=utf-8><body style="margin:0">
<div id=pad style="position:fixed;inset:0;background:#eee"></div>
<script>
window.__moves=[]; window.__cap=[]; window.__mm=[];
const pad=document.getElementById('pad');
pad.addEventListener('pointermove', e=>{
  window.__moves.push(e.buttons);
  if((e.buttons&1) && !pad.hasPointerCapture(e.pointerId)){
    try{ pad.setPointerCapture(e.pointerId); window.__cap.push('ok'); }
    catch(err){ window.__cap.push(err.name); }
  }
});
document.addEventListener('mousemove',
  e=>window.__mm.push([Math.round(e.clientX),Math.round(e.clientY)]));
</script></body>"""


@pytest.fixture
async def tab():
    result = browser_start(headless=True, temp=True, reuse="none")
    assert "error" not in result, result
    port = result["port"]
    browser = None
    try:
        browser = await connect_browser(port=port)
        the_tab = await get_active_tab(browser)
        await the_tab.get(
            "data:text/html;base64," + base64.b64encode(_PAGE.encode()).decode()
        )
        await the_tab.sleep(0.3)
        yield the_tab
    finally:
        if browser is not None:
            with contextlib.suppress(Exception):
                await browser.close()
        with contextlib.suppress(Exception):
            browser_stop(port=port)


@pytest.mark.asyncio
async def test_drag_moves_hold_the_button(tab):
    await tab.mouse_drag((100, 100), (300, 300), steps=10)
    moves = await tab.evaluate("window.__moves")
    cap = await tab.evaluate("window.__cap")
    assert moves and set(moves) == {1}, (
        f"every drag move must report buttons=1: {moves}"
    )
    # setPointerCapture during a pointermove must now succeed (pointer is active)
    assert cap and "NotFoundError" not in cap, cap
    assert "ok" in cap, cap


@pytest.mark.asyncio
async def test_click_survives_a_slow_or_failing_pre_move(tab, monkeypatch):
    # A slow/timing-out positioning move must not doom the click — the press +
    # release (the actual action) still fire. Simulate the move raising.

    from ai_dev_browser.core import mouse as _mouse
    from ai_dev_browser.core.mouse import mouse_click

    async def boom(*a, **k):
        raise TimeoutError("CDP command timed out after 5.0s: Input.dispatchMouseEvent")

    # both the human and plain move paths raise; the click must still land
    monkeypatch.setattr(_mouse.human, "mouse_move", boom)
    monkeypatch.setattr(tab, "mouse_move", boom)
    # Use the already loaded page and register before dispatch. A CDP ACK can
    # arrive before the renderer runs the click handler on a loaded CI host.
    await tab.evaluate(
        """window.__clicks=[];
document.getElementById('pad').addEventListener('click', e=>{
  document.title='HIT';
  window.__clicks.push({trusted:e.isTrusted,x:e.clientX,y:e.clientY});
}); true;"""
    )
    assert await mouse_click(tab, 40, 40, move=True) is True
    state = await tab.evaluate(
        """new Promise(resolve=>{
const deadline=performance.now()+2000;
function check(){
  if(window.__clicks.length || performance.now()>=deadline){
    resolve({title:document.title,clicks:window.__clicks});
  } else setTimeout(check,20);
} check(); })""",
        await_promise=True,
    )
    assert state == {
        "title": "HIT",
        "clicks": [{"trusted": True, "x": 40, "y": 40}],
    }, ("a single trusted click must land despite the move failing", state)


@pytest.mark.asyncio
async def test_cdp_send_dispatches_a_click_with_enum_button(tab):
    # The raw escape hatch must send a click: button="left" (a str) is coerced to
    # the MouseButton enum instead of failing on .to_json().
    import json as _json

    from ai_dev_browser.core.cdp import cdp_send

    await tab.get(
        "data:text/html,<body style='margin:0'>"
        "<div id=t style='width:100vw;height:100vh' "
        "onclick=\"document.title='RAW'\">x</div></body>"
    )
    await tab.sleep(0.2)
    for etype in ("mousePressed", "mouseReleased"):
        res = await cdp_send(
            tab,
            "Input.dispatchMouseEvent",
            _json.dumps(
                {"type": etype, "button": "left", "x": 40, "y": 40, "clickCount": 1}
            ),
        )
        assert "error" not in res, res
    assert await tab.evaluate("document.title") == "RAW"


@pytest.mark.asyncio
async def test_mouse_move_starts_from_last_position_not_origin(tab):
    await tab.mouse_move(400, 300, steps=8)
    await tab.evaluate("window.__mm=[]")
    await tab.mouse_move(420, 320, steps=8)
    mm = await tab.evaluate("window.__mm")
    assert mm, "no moves recorded"
    fx, fy = mm[0]
    # first sample of the 2nd move must be near the prior endpoint (400,300),
    # not swept from the origin (which would land near 42,40 on step 1 of 8).
    assert fx > 380 and fy > 280, f"2nd move swept from origin: first sample {mm[0]}"
