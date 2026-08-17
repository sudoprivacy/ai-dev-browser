"""page_screenshot returns `scale_factor`, and mouse_click(screenshot=) uses it
to turn image-pixel coordinates into a TRUSTED click — the escape hatch for
opaque / canvas UIs (an HTML5-canvas ERP console) where DOM/xpath/AX find
nothing.

Reported on 金蝶云星空's canvas main console: no readable DOM, so navigation must
be visual — screenshot, locate the text's pixel position, click it. Two things
have to hold: (1) the caller can see the scale factor to convert coordinates,
and (2) a click computed from screenshot pixels actually lands, trusted, under
a scaled display (the reporter's ~1.25x DPR mismatch).

The fixture pins a button at a known CSS box and emulates deviceScaleFactor
1.25, so the screenshot is bigger than CSS and a naive un-scaled click would
miss.
"""

from __future__ import annotations

import base64
import contextlib
import os

import pytest

from ai_dev_browser.cdp import emulation
from ai_dev_browser.core import js_evaluate, mouse_click, page_goto, page_screenshot
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.connection import connect_browser, get_active_tab

SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)

_HTML = (
    "<!doctype html><meta charset=utf-8><body style='margin:0'>"
    "<button id=b style='position:absolute;left:300px;top:200px;"
    "width:120px;height:40px'>报表</button>"
    "<script>window.__hit=false;document.getElementById('b')"
    ".addEventListener('click',e=>{window.__hit=e.isTrusted});</script></body>"
)
_URL = "data:text/html;base64," + base64.b64encode(_HTML.encode()).decode()


@pytest.fixture(autouse=True)
def _integration_guard():
    if SKIP_INTEGRATION:
        pytest.skip("SKIP_INTEGRATION is set")


@pytest.fixture
async def tab():
    result = browser_start(headless=True, temp=True, reuse="none")
    assert "error" not in result, f"browser_start failed: {result}"
    port = result["port"]
    browser = None
    try:
        browser = await connect_browser(port=port)
        the_tab = await get_active_tab(browser)
        # Emulate a 1.25x display: the screenshot is bigger than CSS, so a click
        # computed from image pixels must be scaled back or it misses.
        await the_tab.send(
            emulation.set_device_metrics_override(
                width=1600,
                height=950,
                device_scale_factor=1.25,
                mobile=False,
                screen_width=1600,
                screen_height=950,
            )
        )
        await page_goto(the_tab, _URL)
        yield the_tab
    finally:
        if browser is not None:
            with contextlib.suppress(Exception):
                await browser.close()
        browser_stop(port=port)


async def test_screenshot_returns_scale_factor(tab, tmp_path):
    shot = await page_screenshot(tab, path=str(tmp_path / "s.png"))
    assert "scale_factor" in shot and shot["scale_factor"], shot
    assert "device_pixel_ratio" in shot, shot
    # Under 1.25x the image is larger than CSS, so image-pixels > CSS → factor > 1.
    assert shot["scale_factor"] > 1.0, shot


async def test_image_pixel_click_lands_trusted(tab, tmp_path):
    """The canvas-nav flow: screenshot → locate target in IMAGE pixels →
    mouse_click(screenshot=) scales to CSS and fires a trusted click."""
    shot = await page_screenshot(tab, path=str(tmp_path / "s.png"))
    sf = shot["scale_factor"]
    # The button's CSS centre is (360, 220); its image-pixel centre is that
    # divided by scale_factor (what a caller reads off the actual image).
    ix, iy = 360 / sf, 220 / sf
    result = await mouse_click(tab, ix, iy, screenshot=str(tmp_path / "s.png"))
    assert result is True
    hit = (await js_evaluate(tab, "window.__hit"))["result"]
    assert hit is True, "image-pixel click did not land a trusted click on the target"


async def test_unscaled_click_would_miss(tab, tmp_path):
    """Contrast pin: without the screenshot= scaling, feeding image-pixel coords
    straight to mouse_click misses — which is why scale_factor matters."""
    shot = await page_screenshot(tab, path=str(tmp_path / "s.png"))
    sf = shot["scale_factor"]
    ix, iy = 360 / sf, 220 / sf
    await js_evaluate(tab, "window.__hit=false")
    await mouse_click(tab, ix, iy)  # no screenshot= → no scaling → wrong CSS point
    hit = (await js_evaluate(tab, "window.__hit"))["result"]
    assert hit is False, "un-scaled image-pixel coords should NOT hit the button"
