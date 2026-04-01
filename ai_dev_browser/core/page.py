"""Page information operations."""

import datetime
import json
from pathlib import Path

from ._tab import Tab
from .config import DEFAULT_SCREENSHOT_DIR

# Optional PIL for image resizing
try:
    from PIL import Image

    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# Max long edge for screenshots. Prevents downstream image scaling (e.g., by LLM APIs)
# from breaking coordinate alignment with mouse_click().
MAX_SCREENSHOT_LONG_EDGE = 1568


def read_screenshot_metadata(path: str) -> dict:
    """Read ai_dev_browser metadata embedded in a PNG screenshot.

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


async def js_exec(tab: Tab, expression: str) -> dict:
    """Execute JavaScript in the page context.

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


async def screenshot(
    tab: Tab,
    path: str | None = None,
    full_page: bool = False,
    css_scale: bool = True,
    max_long_edge: int = MAX_SCREENSHOT_LONG_EDGE,
) -> dict:
    """Take a screenshot of the page.

    Args:
        tab: Tab instance
        path: Path to save screenshot (default: ./screenshots/{timestamp}.png)
        full_page: If True, capture full page (not just viewport)
        css_scale: If True (default), resize screenshot so pixel coordinates
                   match CSS/click coordinates. Handles both DPR>1 (Retina)
                   and large viewport (>1568px) scenarios.
        max_long_edge: Maximum long edge in pixels (default: 1568, matching
                       Claude API's auto-scale threshold). Set to 0 to disable.

    Returns:
        dict with:
        - path: file path
        - size: file size in bytes
        - width, height: final image dimensions
        - device_pixel_ratio: browser DPR
        - scale_factor: multiply screenshot coords by this to get click coords.
                        1.0 means screenshot coords = click coords directly.
                        >1.0 means image was downscaled (e.g., 1.65 for 2517→1527).

    Note:
        When scale_factor=1.0, screenshot coordinates can be used directly for
        mouse_click(). When scale_factor>1.0:
            click_x = screenshot_x * scale_factor
            click_y = screenshot_y * scale_factor
    """
    if path is None:
        DEFAULT_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = str(DEFAULT_SCREENSHOT_DIR / f"{ts}.png")

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

        # Step 2: Large viewport scaling — prevent Claude API from
        # doing its own rescaling (which breaks coordinate alignment).
        # Scale down to max_long_edge while preserving aspect ratio.
        target_width = css_width
        target_height = css_height
        if max_long_edge > 0:
            long_edge = max(css_width, css_height)
            if long_edge > max_long_edge:
                ratio = max_long_edge / long_edge
                target_width = int(css_width * ratio)
                target_height = int(css_height * ratio)

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
        "scale_factor": round(scale_factor, 4),
    }


async def get_page_info(tab: Tab) -> dict:
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


async def get_page_html(
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
