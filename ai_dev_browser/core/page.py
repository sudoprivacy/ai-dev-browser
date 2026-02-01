"""Page information operations."""

import json
import tempfile
from pathlib import Path

import nodriver


async def eval_js(tab: nodriver.Tab, expression: str) -> dict:
    """Execute JavaScript in the page.

    Args:
        tab: Tab instance
        expression: JavaScript code to execute

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
    tab: nodriver.Tab,
    path: str | None = None,
    full_page: bool = False,
) -> dict:
    """Take a screenshot of the page.

    Args:
        tab: Tab instance
        path: Path to save screenshot (optional, uses temp file if not provided)
        full_page: If True, capture full page (not just viewport)

    Returns:
        dict with path, size, success
    """
    if path is None:
        path = tempfile.mktemp(suffix=".png")

    await tab.save_screenshot(path, full_page=full_page)

    file_size = Path(path).stat().st_size
    return {
        "path": path,
        "size": file_size,
    }


async def get_page_info(tab: nodriver.Tab) -> dict:
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
    tab: nodriver.Tab,
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
        return await tab.evaluate(f"document.querySelector({repr(selector)})?.outerHTML || ''")
    return await tab.get_content()
