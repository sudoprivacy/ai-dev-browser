"""Page information operations."""

import json
import tempfile
from pathlib import Path

from ._tab import Tab

# Optional PIL for image resizing
try:
    from PIL import Image

    HAS_PIL = True
except ImportError:
    HAS_PIL = False


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
) -> dict:
    """Take a screenshot of the page.

    Args:
        tab: Tab instance
        path: Path to save screenshot (optional, uses temp file if not provided)
        full_page: If True, capture full page (not just viewport)
        css_scale: If True (default), resize screenshot to CSS pixel dimensions.
                   This makes screenshot coordinates directly usable for clicking.
                   If False, return original device pixel resolution.

    Returns:
        dict with path, size, width, height, device_pixel_ratio

    Note:
        When css_scale=True (default), screenshot coordinates can be used directly
        for mouse clicks without conversion. This matches how Claude in Chrome works.

        When css_scale=False, to convert screenshot pixel coordinates to click coordinates:
            click_x = pixel_x / device_pixel_ratio
            click_y = pixel_y / device_pixel_ratio
    """
    if path is None:
        path = tempfile.mktemp(suffix=".png")

    # Get viewport info and device pixel ratio for coordinate mapping
    viewport_info = await tab.evaluate(
        "JSON.stringify({width: window.innerWidth, height: window.innerHeight, "
        "devicePixelRatio: window.devicePixelRatio})"
    )
    vp = json.loads(viewport_info)
    dpr = vp["devicePixelRatio"]

    await tab.save_screenshot(path, full_page=full_page)

    # Resize to CSS dimensions if requested and PIL is available
    if css_scale and HAS_PIL and dpr > 1:
        with Image.open(path) as img:
            orig_width, orig_height = img.size
            new_width = int(orig_width / dpr)
            new_height = int(orig_height / dpr)
            resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            resized.save(path)
            width, height = new_width, new_height
    else:
        # Return original dimensions
        if HAS_PIL:
            with Image.open(path) as img:
                width, height = img.size
        else:
            width = int(vp["width"] * dpr)
            height = int(vp["height"] * dpr)

    file_size = Path(path).stat().st_size
    return {
        "path": path,
        "size": file_size,
        "width": width,
        "height": height,
        "device_pixel_ratio": dpr,
        "css_scaled": css_scale and HAS_PIL and dpr > 1,
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
