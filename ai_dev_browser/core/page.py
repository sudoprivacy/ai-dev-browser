"""Page information operations."""

import datetime
import json
import os
from pathlib import Path

from ._tab import Tab
from .config import DEFAULT_SCREENSHOT_DIR


# Env var for consumers (sudowork, etc.) to inject a persistent output directory
# so LLMs don't have to learn host-specific scratch/persistent conventions.
# When unset, falls back to DEFAULT_SCREENSHOT_DIR (./screenshots/).
_OUTPUT_DIR_ENV = "AI_DEV_BROWSER_OUTPUT_DIR"


def _resolve_default_screenshot_dir() -> Path:
    """Resolve the default screenshot directory.

    Order: AI_DEV_BROWSER_OUTPUT_DIR env var (consumer-injected persistent
    path) → DEFAULT_SCREENSHOT_DIR (./screenshots/ relative to cwd).
    """
    env_dir = os.environ.get(_OUTPUT_DIR_ENV)
    if env_dir:
        return Path(env_dir).expanduser()
    return DEFAULT_SCREENSHOT_DIR


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
    """Read ai_dev_browser metadata embedded in a PNG page_screenshot.

    Returns dict with scale_factor, viewport dimensions, etc.
    Returns empty dict if not a PNG or metadata not found.
    """
    if not HAS_PIL or not path.endswith(".png"):
        return {}
    try:
        with Image.open(path) as img:
            raw = img.text.get("ai_dev_browser")
            if raw:
                return json.loads(raw)
    except Exception:
        pass
    return {}


async def js_evaluate(tab: Tab, expression: str) -> dict:
    """Execute JavaScript in the page context.

    Before reaching for raw JS, check whether a CLI tool already covers your
    intent — most locator / action cases do:

      - Locate + act by html id:    `click_by_html_id` / `find_by_html_id`
      - Locate + act by XPath:      `click_by_xpath` / `find_by_xpath`
      - Locate + act by text:       `click_by_text` / `type_by_text`
      - Locate + act by AX ref:     `click_by_ref` / `type_by_ref` (after
                                    `page_discover`)

    Use `js_evaluate` only for genuinely custom JS that none of the above
    express. For **multi-line** scripts the shell quoting in
    `--expression "..."` gets painful fast — prefer the Python API:

        from ai_dev_browser.core import js_evaluate
        result = await js_evaluate(tab, expression='''
            // multi-line JS here, no shell escaping
        ''')

    Args:
        tab: Tab instance
        expression: JavaScript code to execute. Result of last expression is returned.

    Returns:
        dict with result (serializable) or error
    """
    result = await tab.evaluate(expression)
    # Try to serialize result
    try:
        json.dumps(result)
        return {"result": result}
    except (TypeError, ValueError):
        return {"result": str(result)}


async def page_screenshot(
    tab: Tab,
    path: str | None = None,
    full_page: bool = False,
    css_scale: bool = True,
    max_long_edge: int = MAX_SCREENSHOT_LONG_EDGE,
    max_total_pixels: int = MAX_SCREENSHOT_TOTAL_PIXELS,
) -> dict:
    """Take a page_screenshot of the page.

    Args:
        tab: Tab instance
        path: Path to save page_screenshot. When omitted, defaults to
              `$AI_DEV_BROWSER_OUTPUT_DIR/{timestamp}.png` if the env var
              is set (consumers like sudowork use this to inject a
              persistent output directory), otherwise
              `./screenshots/{timestamp}.png` relative to cwd.
        full_page: If True, capture full page (not just viewport)
        css_scale: If True (default), resize page_screenshot so pixel coordinates
                   match CSS/click coordinates. Handles both DPR>1 (Retina)
                   and large viewport scenarios.
        max_long_edge: Maximum long edge in pixels (default: 1568). Set to 0
                       to disable. Different models have different limits:
                       Claude=1568, GPT-4o=2048, Gemini=0 (unlimited).
        max_total_pixels: Maximum total pixels (default: 1,150,000). Set to 0
                          to disable. Claude API constraint; checked after
                          max_long_edge scaling.

    Returns:
        dict with path, size, width, height

    Note:
        Pass the page_screenshot path to mouse_click(--page_screenshot) for automatic
        coordinate scaling. Scaling metadata is embedded in the PNG file.
    """
    if path is None:
        out_dir = _resolve_default_screenshot_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = str(out_dir / f"{ts}.png")

    # Get viewport info and device pixel ratio for coordinate mapping
    viewport_info = await tab.evaluate(
        "JSON.stringify({width: window.innerWidth, height: window.innerHeight, "
        "devicePixelRatio: window.devicePixelRatio})"
    )
    vp = json.loads(viewport_info)
    dpr = vp["devicePixelRatio"]

    await tab.save_screenshot(path, full_page=full_page)

    scale_factor = 1.0

    if css_scale and HAS_PIL:
        with Image.open(path) as img:
            orig_width, orig_height = img.size

        # Step 1: DPR scaling — convert device pixels to CSS pixels
        css_width = orig_width
        css_height = orig_height
        if dpr > 1:
            css_width = int(orig_width / dpr)
            css_height = int(orig_height / dpr)

        # Step 2: Scale down to fit within limits (preserving aspect ratio).
        target_width = css_width
        target_height = css_height

        # 2a: Long edge limit
        if max_long_edge > 0:
            long_edge = max(target_width, target_height)
            if long_edge > max_long_edge:
                ratio = max_long_edge / long_edge
                target_width = int(target_width * ratio)
                target_height = int(target_height * ratio)

        # 2b: Total pixels limit (checked after long edge)
        if max_total_pixels > 0:
            total = target_width * target_height
            if total > max_total_pixels:
                import math

                ratio = math.sqrt(max_total_pixels / total)
                target_width = int(target_width * ratio)
                target_height = int(target_height * ratio)

        # Apply scaling if needed
        if target_width != orig_width or target_height != orig_height:
            with Image.open(path) as img:
                resized = img.resize(
                    (target_width, target_height), Image.Resampling.LANCZOS
                )
                resized.save(path)

        if target_width > 0:
            scale_factor = vp["width"] / target_width

        width, height = target_width, target_height
    else:
        if HAS_PIL:
            with Image.open(path) as img:
                width, height = img.size
        else:
            width = int(vp["width"] * dpr)
            height = int(vp["height"] * dpr)

    # Embed metadata in PNG so mouse_click can auto-scale coordinates
    if HAS_PIL and path.endswith(".png"):
        from PIL.PngImagePlugin import PngInfo

        meta = PngInfo()
        meta.add_text(
            "ai_dev_browser",
            json.dumps(
                {
                    "scale_factor": round(scale_factor, 6),
                    "viewport_width": vp["width"],
                    "viewport_height": vp["height"],
                    "image_width": width,
                    "image_height": height,
                    "device_pixel_ratio": dpr,
                }
            ),
        )
        with Image.open(path) as img:
            img.save(path, pnginfo=meta)

    file_size = Path(path).stat().st_size
    return {
        "path": path,
        "size": file_size,
        "width": width,
        "height": height,
    }


async def page_info(tab: Tab) -> dict:
    """Get current page information.

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
    """Get page HTML content with metadata.

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
