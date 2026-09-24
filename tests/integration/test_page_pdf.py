"""page_pdf produces a vector PDF at an exact physical page size (E2E).

Mirrors the ShareOne acceptance test: a 90x54mm card with `@page` size and a
full-bleed background — assert the PDF MediaBox is 255.12 x 153.07 pt (the
metric card in points), that it's a single vector page (fonts embedded, text
not rasterised), and that unit parsing + presets + fail-loud all hold.
Launches a real headless Chrome.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import re

import pytest

from ai_dev_browser.core import connect_browser, get_active_tab
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.page import page_pdf

# 90x54mm card: @page declares the exact size, full-bleed dark background, text.
_CARD = """<!doctype html><html><head><meta charset=utf-8><style>
@page { size: 90mm 54mm; margin: 0 }
html,body { margin: 0 }
.card { width: 90mm; height: 54mm; background: #10314f; color: #fff;
        display: flex; align-items: center; justify-content: center;
        font: 14pt serif }
</style></head><body><div class="card">Vector Card 90x54</div></body></html>"""


def _mediabox(path: str) -> tuple[float, float, bytes]:
    data = open(path, "rb").read()
    m = re.search(
        rb"/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\]", data
    )
    assert m, "no /MediaBox in output PDF"
    return float(m.group(3)), float(m.group(4)), data


@pytest.fixture
async def tab(tmp_path):
    result = browser_start(headless=True, temp=True, reuse="none")
    assert "error" not in result, result
    port = result["port"]
    browser = None
    try:
        browser = await connect_browser(port=port)
        the_tab = await get_active_tab(browser)
        url = "data:text/html;base64," + base64.b64encode(_CARD.encode()).decode()
        await the_tab.get(url)
        await asyncio.sleep(0.3)
        yield the_tab
    finally:
        if browser is not None:
            with contextlib.suppress(Exception):
                await browser.close()
        with contextlib.suppress(Exception):
            browser_stop(port=port)


@pytest.mark.asyncio
async def test_prefer_css_page_size_is_pixel_exact(tab, tmp_path):
    # The FR acceptance test: @page size honored exactly (255.12 x 153.07 pt).
    out = str(tmp_path / "card_css.pdf")
    res = await page_pdf(tab, path=out, prefer_css_page_size=True)
    assert res["pages"] == 1, res
    w, h, data = _mediabox(out)
    assert w == pytest.approx(255.12, abs=0.5), w  # 90mm
    assert h == pytest.approx(153.07, abs=0.5), h  # 54mm
    assert data[:5] == b"%PDF-", "not a PDF"
    assert b"/Font" in data, "text must be vector (fonts embedded), not rasterised"
    # the achieved trim is folded into the return (5a) — no need to re-open
    assert res["page_size_pt"][0] == pytest.approx(255.12, abs=0.5), res
    assert res["page_size_mm"][0] == pytest.approx(90.0, abs=0.2), res
    assert res["page_size_mm"][1] == pytest.approx(54.0, abs=0.2), res


@pytest.mark.asyncio
async def test_paper_preset_and_units_produce_a_card(tab, tmp_path):
    # The convenience path is now pixel-exact too (injected @page), so the
    # obvious `--paper card-cn` call lands on 255.12 x 153.07, not Chrome's
    # rounded 256.08 x 154.08.
    out = str(tmp_path / "card_preset.pdf")
    res = await page_pdf(tab, path=out, paper="card-cn")
    assert res["pages"] == 1, res
    w, h, _ = _mediabox(out)
    assert w == pytest.approx(255.12, abs=0.5), w
    assert h == pytest.approx(153.07, abs=0.5), h

    # explicit unit-suffixed size matches the preset (same physical size)
    out2 = str(tmp_path / "card_units.pdf")
    await page_pdf(tab, path=out2, paper_width="90mm", paper_height="54mm")
    w2, h2, _ = _mediabox(out2)
    assert w2 == pytest.approx(w, abs=0.5) and h2 == pytest.approx(h, abs=0.5)


@pytest.mark.asyncio
async def test_explicit_size_is_exact_without_page_css(tab, tmp_path):
    # A page that declares NO @page of its own: only the injected @page can make
    # the explicit size exact. Proves the fix (not the document's CSS) — the
    # obvious `--paper card-cn` lands on 255.12, not Chrome's rounded 256.08.
    plain = "<!doctype html><meta charset=utf-8><body style='margin:0'>x</body>"
    url = "data:text/html;base64," + base64.b64encode(plain.encode()).decode()
    await tab.get(url)
    await asyncio.sleep(0.2)
    out = str(tmp_path / "plain_card.pdf")
    res = await page_pdf(tab, path=out, paper_width="90mm", paper_height="54mm")
    w, h, _ = _mediabox(out)
    assert w == pytest.approx(255.12, abs=0.5), w
    assert h == pytest.approx(153.07, abs=0.5), h
    assert res["page_size_mm"][0] == pytest.approx(90.0, abs=0.2), res


@pytest.mark.asyncio
async def test_print_background_flag_changes_output(tab, tmp_path):
    # print_background defaults True; turning it off must change the rendered
    # content (the full-bleed background is dropped).
    on = str(tmp_path / "bg_on.pdf")
    off = str(tmp_path / "bg_off.pdf")
    await page_pdf(tab, path=on, paper="card-cn", print_background=True)
    await page_pdf(tab, path=off, paper="card-cn", print_background=False)
    assert open(on, "rb").read() != open(off, "rb").read(), "flag had no effect"


@pytest.mark.asyncio
async def test_bad_unit_fails_loud(tab, tmp_path):
    # A bad size must raise, never silently render the wrong trim.
    with pytest.raises(ValueError):
        await page_pdf(tab, path=str(tmp_path / "x.pdf"), paper_width="90furlong")
    with pytest.raises(ValueError):
        await page_pdf(tab, path=str(tmp_path / "x.pdf"), paper="not-a-preset")
