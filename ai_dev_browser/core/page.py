"""Page information operations."""

import asyncio
import base64
import datetime
import json
import re
from pathlib import Path

from ._tab import Tab
from .config import resolve_output_dir
from .errors import JsEvaluationError


# Optional PIL for image resizing
try:
    from PIL import Image

    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# Default page_screenshot limits matching Claude's effective visual resolution.
# Claude API accepts up to 1568px, but the vision encoder works at ~768px
# internally. Anthropic's computer_use docs recommend 1024-1280px for
# accurate coordinate estimation. 1568px causes ~30-50px systematic drift.
MAX_SCREENSHOT_LONG_EDGE = 1280
MAX_SCREENSHOT_TOTAL_PIXELS = 1_150_000


def read_screenshot_metadata(path: str) -> dict:
    """Read ai_dev_browser metadata embedded in a saved screenshot.

    Returns dict with scale_factor, viewport dimensions, etc.
    Returns empty dict if PIL is unavailable, the file is missing,
    or metadata isn't present. Supports both PNG (text chunk) and
    JPEG (EXIF UserComment) — single entry point so consumers like
    `mouse._scale_coords` stay format-agnostic.
    """
    if not HAS_PIL:
        return {}
    from . import _image_cap

    return _image_cap.read_metadata(path)


async def js_evaluate(tab: Tab, expression: str, frame: str | None = None) -> dict:
    """Use when: NO specific tool fits — the last-resort raw JS escape
    hatch. Works equally for **read** expressions (`document.title`,
    `innerText`) and **side-effect** expressions (`.click()`, `.submit()`,
    DOM mutations) — the return dict captures *everything* observable
    during the eval, not just the expression value.

    Pass `frame` (a URL substring or CDP target id) to run the expression
    **inside a cross-origin iframe** — government / bank sites embed forms in
    OOPIFs that the top document (and `find_by_text` / `click_by_text`) can't
    reach ("Cross-origin iframes are not scanned"). `js_evaluate(expr,
    frame="chinatax.gov")` runs `expr` in that frame's own context, where
    `document` is the iframe's document. Same-origin iframes don't need this.

    Before picking this: the locate+act combinations below cover almost
    all intents atomically and are more specific:

      - Locate + act by html id:    `click_by_html_id` / `find_by_html_id`
      - Locate + act by XPath:      `click_by_xpath` / `find_by_xpath`
      - Locate + act by text:       `click_by_text` / `type_by_text`
      - Locate + act by AX ref:     `click_by_ref` / `type_by_ref` (after
                                    `page_discover`)

    For **multi-line** custom JS the shell quoting in `--expression "..."`
    gets painful — prefer the Python API:

        from ai_dev_browser.core import js_evaluate
        result = await js_evaluate(tab, expression='''
            // multi-line JS here, no shell escaping
        ''')

    A page-side `throw` **fails this call** — it does not come back as data.
    That makes the expression usable directly as an assertion:

        js_evaluate(tab, "if (count !== 3) throw new Error('want 3, got ' + count)")

    Args:
        tab: Tab instance
        expression: JavaScript code to execute. Result of last expression
            is returned. `console.log` / `warn` / `error` / `info` output
            during the eval is captured separately.
        frame: Optional cross-origin iframe to run inside — a substring of
            the frame's URL (e.g. `"chinatax.gov"`) or its CDP target id.
            Omit for the top page. A no-match lists the page's real
            cross-origin frames so you can retry with a correct substring.

    Returns:
        dict with:

          - `result`: the expression's evaluated value (may be `None` if
            the expression is a void side-effect like `.click()`).
            Objects and arrays arrive as plain dicts / lists. A value with
            no Python representation (DOM node, function, pending promise)
            arrives as `{"__js_type__": ..., "hint": ...}` telling you what
            it was and how to ask for it properly — ignore it if you only
            wanted the side effect.
          - `console`: list of `{level, text}` entries emitted during
            the eval, if any (only present when non-empty)
          - `url_before` / `url_after` / `title_after` / `navigated`:
            top-level navigation observables, same shape as
            `click_by_*`. `navigated=True` iff URL changed.

    Failure:
        The expression threw. The error text carries the JS message, the JS
        stack, the expression, and any console output emitted before the throw
        — read it rather than re-running with added logging. A SyntaxError
        naming `return` means you wrote a bare `return` at top level, which is
        illegal outside a function: drop it (the last expression is the result)
        or wrap the body in an IIFE `(() => { ... })()`. If you passed `frame`
        and it didn't match, the error lists the page's real cross-origin
        frames — retry with any substring of one of those URLs.

    Example:
        # Read — result field carries the answer
        await js_evaluate(tab, "document.title")
        # → {"result": "...", "url_before": ..., "navigated": False}

        # Side effect — navigated/url_after + console confirm what happened
        await js_evaluate(tab, "document.querySelector('#login').click()")
        # → {"result": None, "url_before": "/login", "url_after": "/home",
        #    "navigated": True, "title_after": "Home"}

        # Debugging — console lines captured
        await js_evaluate(tab, "console.log('x=', x); x + 1")
        # → {"result": 2, "console": [{"level": "log", "text": "x= 1"}], ...}

        # Assertion — a throw raises JsEvaluationError, it is never a result
        await js_evaluate(tab, "if (!document.querySelector('#ok')) throw new Error('no #ok')")
    """
    from ai_dev_browser.cdp import runtime

    from .elements import _POST_CLICK_NAV_DELAY, _capture_page_state

    # Cross-origin iframe: route the eval into that OOPIF's own CDP session.
    session_id = await tab.frame_session(frame) if frame else None

    before = await _capture_page_state(tab)

    console_msgs: list[dict] = []

    def _stringify_arg(arg) -> str:
        # Runtime.RemoteObject: value (primitive) / description / unserializable_value
        val = getattr(arg, "value", None)
        if val is not None:
            try:
                return json.dumps(val, ensure_ascii=False)
            except (TypeError, ValueError):
                return str(val)
        desc = getattr(arg, "description", None)
        if desc:
            return str(desc)
        unser = getattr(arg, "unserializable_value", None)
        if unser:
            return str(unser)
        return ""

    def on_console(event):
        level = getattr(event, "type_", "log")
        text = " ".join(_stringify_arg(a) for a in event.args)
        console_msgs.append({"level": level, "text": text})

    # Runtime.enable() is idempotent and required for consoleAPICalled events.
    await tab.send(runtime.enable(), session_id=session_id)
    tab.add_handler(runtime.ConsoleAPICalled, on_console)

    try:
        result_value = await tab.evaluate(expression, session_id=session_id)
    except JsEvaluationError as e:
        # Console lines emitted before the throw are the trail of how the page
        # reached the failing state. They belong with the failure, not in a
        # success dict the caller never reads.
        e.console = console_msgs
        raise
    finally:
        tab.remove_handler(runtime.ConsoleAPICalled, on_console)

    # Give any navigation triggered by the eval a moment to commit,
    # mirroring click_by_*'s _POST_CLICK_NAV_DELAY so URL snapshots
    # reflect the post-action state.
    await asyncio.sleep(_POST_CLICK_NAV_DELAY)

    try:
        after = await _capture_page_state(tab)
    except Exception:
        # Context destroyed mid-read (full-page nav) — we know URL changed
        after = {"url": None, "title": None}

    url_before = before.get("url", "") if isinstance(before, dict) else ""
    url_after = after.get("url") if isinstance(after, dict) else None
    title_after = after.get("title", "") if isinstance(after, dict) else ""
    navigated = bool(url_before) and url_after is not None and url_after != url_before

    out: dict = {
        "result": result_value,
        "url_before": url_before,
        "url_after": url_after,
        "title_after": title_after,
        "navigated": navigated,
    }
    if console_msgs:
        out["console"] = console_msgs
    return out


async def page_screenshot(
    tab: Tab,
    path: str | None = None,
    full_page: bool = False,
    css_scale: bool = True,
    max_long_edge: int = MAX_SCREENSHOT_LONG_EDGE,
    max_total_pixels: int = MAX_SCREENSHOT_TOTAL_PIXELS,
    image_cap: dict | None = None,
) -> dict:
    """Use when: you need pixels for visual reasoning, coordinate-based
    clicking, or evidence of current state. Returns `{path, size, width,
    height, scale_factor, device_pixel_ratio}` — the path is the saved PNG
    you can read with vision.

    This is the escape hatch for **opaque / canvas UIs** with no readable DOM
    (e.g. an HTML5-canvas ERP console where `find_by_text` / xpath find
    nothing): screenshot → locate the target's IMAGE-pixel position yourself
    (your own vision / OCR) → `mouse_click(ix, iy, screenshot=path)`, which
    applies `scale_factor` and fires a trusted click. `scale_factor` is also in
    the return if you'd rather convert coordinates by hand
    (CSS = image-pixel * scale_factor).

    For verifying a click caused navigation, the click_* tools already
    return `navigated` / `url_after` — screenshot is only needed when
    you actually need to see pixels.

    Args:
        tab: Tab instance
        path: Path to save page_screenshot. When omitted, defaults to
              `$AI_DEV_BROWSER_OUTPUT_DIR/{timestamp}.png` if the env var
              is set, otherwise `./output/{timestamp}.png` relative to cwd.
        full_page: If True, capture full page (not just viewport)
        css_scale: If True (default), resize page_screenshot so pixel coordinates
                   match CSS/click coordinates. Handles both DPR>1 (Retina)
                   and large viewport scenarios.
        max_long_edge: Maximum long edge in pixels (default: 1568). Set to 0
                       to disable. Different models have different limits:
                       Claude=1568, GPT-4o=2048, Gemini=0 (unlimited).
                       Ignored when `image_cap` is provided.
        max_total_pixels: Maximum total pixels (default: 1,150,000). Set to 0
                          to disable. Claude API constraint; checked after
                          max_long_edge scaling. Ignored when `image_cap`
                          is provided.
        image_cap: Per-call cap the caller wants the screenshot to
                   fit — typically the accept-limit of whichever
                   downstream consumer (LLM API, upload endpoint,
                   storage tier) will receive the image. When provided,
                   fully overrides `max_long_edge` / `max_total_pixels`
                   so the screenshot targets the *caller's* cap rather
                   than this tool's static defaults. Shape:
                   `{"max_bytes": int, "max_dimension": int}` — both
                   optional. `max_bytes` triggers JPEG re-encode with a
                   quality-step search (output ext changes PNG → JPG).
                   `max_dimension` caps the longest edge in pixels.
                   When omitted, falls back to `AI_DEV_BROWSER_IMAGE_CAP_MAX_BYTES`
                   / `AI_DEV_BROWSER_IMAGE_CAP_MAX_DIMENSION` env vars
                   so the enclosing process can pre-set a session-wide
                   default without threading a per-call arg through
                   every tool invocation. Precedence: per-call arg > env > None.

    Returns:
        dict with path, size, width, height, `scale_factor`,
        `device_pixel_ratio`. `scale_factor` maps image pixels → CSS/click
        coords (CSS = image-pixel * scale_factor); `mouse_click(screenshot=)`
        applies it for you. When `image_cap` is provided, also includes
        `format` ('PNG'|'JPEG') and `capped` (bool — False means best-effort,
        smallest produced still missed `max_bytes`).

    Note:
        Pass the screenshot path to mouse_click(--screenshot) for automatic
        coordinate scaling. Scaling metadata is embedded in the file (PNG
        text chunk for .png, EXIF UserComment for .jpg).
    """
    if path is None:
        out_dir = resolve_output_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = str(out_dir / f"{ts}.png")

    # Get viewport info and device pixel ratio for coordinate mapping
    vp = await tab.evaluate(
        "({width: window.innerWidth, height: window.innerHeight, "
        "devicePixelRatio: window.devicePixelRatio})"
    )
    dpr = vp["devicePixelRatio"]

    await tab.save_screenshot(path, full_page=full_page)

    # Resolve image_cap: per-call arg wins, else env var, else None.
    # Injected here rather than at CLI entry so Python-API callers
    # also inherit the env-default.
    if HAS_PIL:
        from . import _image_cap as _img_cap

        image_cap = _img_cap.resolve_cap(image_cap)

    scale_factor = 1.0
    cap_result: dict | None = None

    if css_scale and HAS_PIL:
        with Image.open(path) as img:
            orig_width, orig_height = img.size

        # Step 1: DPR scaling — convert device pixels to CSS pixels.
        # Always applied; this is a fidelity correction, not a cap.
        css_width = orig_width
        css_height = orig_height
        if dpr > 1:
            css_width = int(orig_width / dpr)
            css_height = int(orig_height / dpr)

        target_width = css_width
        target_height = css_height

        if image_cap:
            # image_cap fully overrides the static max_* params: the
            # active LLM's cap is authoritative, not this tool's local
            # default. Apply DPR-normalized resize first (pre-shrinks
            # for the helper), then hand off. apply_image_cap reserves
            # a small headroom for the metadata write below so that the
            # final on-disk JPEG (image bytes + EXIF UserComment) fits
            # under max_bytes — not just the pre-metadata image bytes.
            if (target_width, target_height) != (orig_width, orig_height):
                with Image.open(path) as img:
                    resized = img.resize(
                        (target_width, target_height), Image.Resampling.LANCZOS
                    )
                    resized.save(path)

            from . import _image_cap as _img_cap

            cap_result = _img_cap.apply_image_cap(
                path, image_cap, reserve_bytes_for_metadata=True
            )
            path = cap_result["final_path"]
            width = cap_result["final_width"]
            height = cap_result["final_height"]
        else:
            # Existing static-cap flow (unchanged): max_long_edge then
            # max_total_pixels, both as area-preserving LANCZOS resizes.
            if max_long_edge > 0:
                long_edge = max(target_width, target_height)
                if long_edge > max_long_edge:
                    ratio = max_long_edge / long_edge
                    target_width = int(target_width * ratio)
                    target_height = int(target_height * ratio)

            if max_total_pixels > 0:
                total = target_width * target_height
                if total > max_total_pixels:
                    import math

                    ratio = math.sqrt(max_total_pixels / total)
                    target_width = int(target_width * ratio)
                    target_height = int(target_height * ratio)

            if target_width != orig_width or target_height != orig_height:
                with Image.open(path) as img:
                    resized = img.resize(
                        (target_width, target_height), Image.Resampling.LANCZOS
                    )
                    resized.save(path)

            width, height = target_width, target_height

        if width > 0:
            scale_factor = vp["width"] / width
    else:
        if HAS_PIL:
            with Image.open(path) as img:
                width, height = img.size
        else:
            width = int(vp["width"] * dpr)
            height = int(vp["height"] * dpr)

    # Embed metadata so mouse_click can auto-scale coordinates regardless
    # of output format. _image_cap.write_metadata dispatches by extension
    # (PNG text chunk vs JPEG EXIF UserComment) — single call site here.
    if HAS_PIL:
        from . import _image_cap as _img_cap

        _img_cap.write_metadata(
            path,
            {
                "scale_factor": round(scale_factor, 6),
                "viewport_width": vp["width"],
                "viewport_height": vp["height"],
                "image_width": width,
                "image_height": height,
                "device_pixel_ratio": dpr,
            },
        )

    file_size = Path(path).stat().st_size
    result = {
        "path": path,
        "size": file_size,
        "width": width,
        "height": height,
        # Surface the coordinate mapping so a caller doing its OWN localization
        # (e.g. an LLM/OCR reading text off the image) can convert: a point at
        # image-pixel (ix, iy) is CSS (ix * scale_factor, iy * scale_factor) —
        # which is what mouse_click(screenshot=...) applies automatically.
        "scale_factor": round(scale_factor, 6),
        "device_pixel_ratio": dpr,
    }
    if cap_result is not None:
        result["format"] = cap_result["format"]
        result["capped"] = cap_result["capped"]
    return result


async def page_info(tab: Tab) -> dict:
    """Use when: you need to confirm the current URL / title / readyState
    without triggering a full `page_discover`. Returns `{url, title,
    ready, state}`. Cheap; typical next step is branching on url/title
    to decide the next action.

    Args:
        tab: Tab instance

    Returns:
        dict with url, title, ready state
    """
    url = tab.target.url if hasattr(tab, "target") and tab.target else ""
    title = tab.target.title if hasattr(tab, "target") and tab.target else ""

    try:
        state = await tab.evaluate("document.readyState")
    except Exception:
        state = "unknown"

    return {
        "url": url,
        "title": title,
        "ready": state == "complete",
        "state": state,
    }


async def get_html(
    tab: Tab,
    selector: str | None = None,
) -> str:
    """Get page HTML content.

    Args:
        tab: Tab instance
        selector: If provided, get HTML of specific element

    Returns:
        HTML string
    """
    if selector:
        return await tab.evaluate(
            f"document.querySelector({repr(selector)})?.outerHTML || ''"
        )
    return await tab.get_content()


async def page_html(
    tab: Tab,
    outer: bool = False,
) -> dict:
    """Use when: you need the WHOLE page's HTML (microdata, script tags,
    document structure). If you only need one element's HTML and have a
    `ref`, `html_by_ref` is one call instead of parsing the full
    document. Returns `{html, length}`.

    Args:
        tab: Tab instance
        outer: If True, get outerHTML of document element

    Returns:
        dict with html content and length
    """
    if outer:
        content = await tab.evaluate("document.documentElement.outerHTML")
    else:
        content = await tab.evaluate("document.documentElement.innerHTML")
    return {
        "html": content,
        "length": len(content),
    }


# --- Print-size parsing for page_pdf -----------------------------------------
# CDP Page.printToPDF takes INCHES only; making callers pre-divide by 25.4 is
# exactly the arithmetic that silently produces a wrong trim size. So every
# length here accepts a unit suffix and is converted once, in one place. A bare
# number stays inches (CDP's native unit), so a plain-number caller is unchanged.
_UNIT_TO_INCHES = {
    "in": 1.0,
    "inch": 1.0,
    "inches": 1.0,
    "mm": 1.0 / 25.4,
    "cm": 1.0 / 2.54,
    "pt": 1.0 / 72.0,
    "px": 1.0 / 96.0,  # CSS reference pixel
}

# Physical page presets as (width, height) UNIT STRINGS — parsed through the
# same path as an explicit size, so every number lives in exactly one place.
# Portrait; use landscape= to rotate.
_PAPER_PRESETS = {
    "letter": ("8.5in", "11in"),
    "legal": ("8.5in", "14in"),
    "tabloid": ("11in", "17in"),
    "a3": ("297mm", "420mm"),
    "a4": ("210mm", "297mm"),
    "a5": ("148mm", "210mm"),
    "a6": ("105mm", "148mm"),
    "card-cn": ("90mm", "54mm"),  # Chinese business card
    "card-intl": ("85mm", "55mm"),  # ISO/EU business card
    "card-us": ("3.5in", "2in"),  # US business card
}

_LENGTH_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([a-zA-Z]*)\s*$")


def _to_inches(value: str | float | int | None, field: str) -> float | None:
    """Parse a physical length to inches. `None` → None; a number → inches
    (CDP's native unit); a string may carry a unit suffix (`"90mm"`, `"3.5in"`,
    `"21cm"`, `"72pt"`). Raises ValueError on an unparsable value or unknown
    unit — a bad size must fail loud, never silently render the wrong trim."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = _LENGTH_RE.match(str(value))
    if not m:
        raise ValueError(
            f"{field}: cannot parse length {value!r} — use e.g. '90mm', '3.5in', "
            "or a bare number in inches"
        )
    unit = (m.group(2) or "in").lower()
    if unit not in _UNIT_TO_INCHES:
        allowed = ", ".join(sorted(set(_UNIT_TO_INCHES) - {"inch", "inches"}))
        raise ValueError(
            f"{field}: unknown unit {unit!r} in {value!r} — use one of {allowed}"
        )
    return float(m.group(1)) * _UNIT_TO_INCHES[unit]


async def page_pdf(
    tab: Tab,
    path: str | None = None,
    paper: str | None = None,
    paper_width: str | None = None,
    paper_height: str | None = None,
    margin: str | None = None,
    margin_top: str | None = None,
    margin_bottom: str | None = None,
    margin_left: str | None = None,
    margin_right: str | None = None,
    landscape: bool = False,
    print_background: bool = True,
    prefer_css_page_size: bool = False,
    scale: float = 1.0,
    page_ranges: str = "",
) -> dict:
    """Use when: you need a print-quality **vector** PDF at an exact physical
    page size — a card, certificate, invoice, label, contract. Text stays
    selectable and fonts embedded, unlike `page_screenshot` (which rasterises).
    Returns `{path, size, pages}`; the decoded PDF is written to `path`, never
    handed back as a string.

    Sizes accept a unit suffix — `paper_width="90mm"`, `margin="0.25in"`,
    `paper="a4"` — and a bare number is inches (CDP's native unit). Defaults are
    print-appropriate where CDP's silently are not: backgrounds print
    (`print_background` True vs CDP's False, which drops every background color/
    image — a blank card) and margins are 0 (vs Chrome's 0.4in, which ruins a
    full-bleed design). For a **pixel-exact** physical size, have the template
    declare its own `@page { size: 90mm 54mm }` and set
    `prefer_css_page_size=True` — that is authoritative and exact; an explicit
    `paper` / `paper_width` size is honored only to within Chrome's sub-point
    print rounding (a metric/fractional size can land <1pt off).

    Args:
        tab: Tab instance
        path: Output file path. When omitted, auto-generates `{timestamp}.pdf`
            in `$AI_DEV_BROWSER_OUTPUT_DIR` (if set) or `./output/` relative to
            cwd.
        paper: Named size preset — letter, legal, tabloid, a3, a4, a5, a6,
            card-cn (90×54mm), card-intl (85×55mm), card-us (3.5×2in). Portrait;
            use `landscape` to rotate. Explicit `paper_width`/`paper_height`
            override it. Default None → letter.
        paper_width: Page width with an optional unit suffix (`"210mm"`,
            `"8.5in"`, `"21cm"`, `"595pt"`); a bare number is inches. Overrides
            `paper`.
        paper_height: Page height, same units as `paper_width`.
        margin: Shorthand for all four margins (with units). A per-side
            `margin_*` overrides it. Default None → 0 on every side.
        margin_top: Top margin (with units). Overrides `margin`. Default 0.
        margin_bottom: Bottom margin. Default 0.
        margin_left: Left margin. Default 0.
        margin_right: Right margin. Default 0.
        landscape: Rotate paper to landscape. Default False (portrait).
        print_background: Print background graphics (colors, images). Default
            True — CDP defaults this False, which silently drops every
            background; for a styled template that means a blank page.
        prefer_css_page_size: Let the page's own `@page { size: ... }` CSS win
            over `paper` / `paper_width` / `paper_height`. Default False.
        scale: Scale of the rendering. Default 1.0.
        page_ranges: Pages to print, e.g. "1-5", "1,3,5-9". Empty (default) =
            all pages.

    Returns:
        dict with `path`, `size` (bytes), `pages`, and the achieved trim as
        `page_size_pt` `[w, h]` (PDF points) + `page_size_mm` `[w, h]` — so you
        confirm the physical size landed without re-opening the PDF.

    Failure:
        "PrintToPDF is not available" means the browser is in headed mode —
        restart with `browser_start --headless` (or set
        `AI_DEV_BROWSER_HEADLESS=1`). An unparsable size (bad number or unknown
        unit) fails loud with `error_code: validation` — fix the value, e.g.
        `"90mm"` / `"3.5in"` / a bare number in inches.
    """
    from ai_dev_browser.cdp import page as cdp_page

    # Resolve the physical size: an explicit width/height wins over a `paper`
    # preset, which wins over the letter default. Each length accepts a unit.
    base_w, base_h = _PAPER_PRESETS["letter"]
    if paper is not None:
        key = paper.strip().lower()
        if key not in _PAPER_PRESETS:
            allowed = ", ".join(sorted(_PAPER_PRESETS))
            raise ValueError(
                f"paper: unknown preset {paper!r} — use one of {allowed}, or pass "
                "paper_width/paper_height"
            )
        base_w, base_h = _PAPER_PRESETS[key]
    width_in = _to_inches(
        paper_width if paper_width is not None else base_w, "paper_width"
    )
    height_in = _to_inches(
        paper_height if paper_height is not None else base_h, "paper_height"
    )

    # Margins: a per-side value wins over the `margin` shorthand, which defaults
    # to 0 (Chrome's 0.4in default ruins a full-bleed card).
    def _side(side_val, name):
        inches = _to_inches(side_val if side_val is not None else margin, name)
        return 0.0 if inches is None else inches

    if path is None:
        out_dir = resolve_output_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = str(out_dir / f"{ts}.pdf")

    result = await tab.send(
        cdp_page.print_to_pdf(
            landscape=landscape,
            print_background=print_background,
            scale=scale,
            paper_width=width_in,
            paper_height=height_in,
            margin_top=_side(margin_top, "margin_top"),
            margin_bottom=_side(margin_bottom, "margin_bottom"),
            margin_left=_side(margin_left, "margin_left"),
            margin_right=_side(margin_right, "margin_right"),
            page_ranges=page_ranges or None,
            prefer_css_page_size=prefer_css_page_size,
        )
    )

    pdf_data, _ = result  # (base64_str, optional_stream_handle)
    pdf_bytes = base64.b64decode(pdf_data)

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(pdf_bytes)

    # Best-effort page count: /Type /Page (leaf) minus /Type /Pages (tree node)
    pages = len(re.findall(rb"/Type\s*/Page\b", pdf_bytes)) - len(
        re.findall(rb"/Type\s*/Pages\b", pdf_bytes)
    )

    result_dict: dict = {
        "path": str(out),
        "size": out.stat().st_size,
        "pages": max(pages, 1),
    }
    # Fold the ACHIEVED physical size into the return (cli-steering 5a): the
    # whole point of this tool is an exact trim, so report the MediaBox that
    # landed — in points (PDF-native) and mm — instead of making the caller
    # re-open the PDF to confirm it.
    mb = re.search(
        rb"/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\]", pdf_bytes
    )
    if mb:
        w_pt = round(float(mb.group(3)) - float(mb.group(1)), 2)
        h_pt = round(float(mb.group(4)) - float(mb.group(2)), 2)
        result_dict["page_size_pt"] = [w_pt, h_pt]
        result_dict["page_size_mm"] = [
            round(w_pt / 72 * 25.4, 2),
            round(h_pt / 72 * 25.4, 2),
        ]
    return result_dict
