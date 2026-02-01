"""Page navigation operations."""

import asyncio
import re
import time
from typing import Optional

import nodriver


async def goto(
    tab: nodriver.Tab,
    url: str,
    new_tab: bool = False,
    wait: bool = True,
) -> dict:
    """Navigate to URL.

    Args:
        tab: Tab instance
        url: URL to navigate to
        new_tab: If True, open in new tab
        wait: If True, wait for page load

    Returns:
        dict with url, title, success
    """
    result_tab = await tab.get(url, new_tab=new_tab)

    if wait:
        await wait_for_load(result_tab)

    try:
        title = await result_tab.evaluate("document.title")
    except Exception:
        title = ""

    return {
        "url": result_tab.target.url if result_tab.target else url,
        "title": title,
        "success": True,
    }


async def back(tab: nodriver.Tab) -> bool:
    """Go back in history."""
    await tab.back()
    return True


async def forward(tab: nodriver.Tab) -> bool:
    """Go forward in history."""
    await tab.forward()
    return True


async def reload(tab: nodriver.Tab, ignore_cache: bool = True) -> bool:
    """Reload the page.

    Args:
        tab: Tab instance
        ignore_cache: If True, ignore browser cache

    Returns:
        True on success
    """
    await tab.reload(ignore_cache=ignore_cache)
    return True


async def wait_for_load(
    tab: nodriver.Tab,
    timeout: float = 30,
    idle_time: float = 0.5,
) -> bool:
    """Wait for page to finish loading.

    Args:
        tab: Tab instance
        timeout: Maximum wait time in seconds
        idle_time: Additional wait after load complete

    Returns:
        True if page loaded, False if timeout
    """
    start = time.time()

    while time.time() - start < timeout:
        try:
            state = await tab.evaluate("document.readyState")
            if state == "complete":
                await asyncio.sleep(idle_time)
                return True
        except Exception:
            pass
        await asyncio.sleep(0.2)

    return False


async def wait_for_url(
    tab: nodriver.Tab,
    pattern: Optional[str] = None,
    exact: Optional[str] = None,
    timeout: float = 30,
) -> dict:
    """Wait for URL to match pattern.

    Args:
        tab: Tab instance
        pattern: URL pattern (substring or regex)
        exact: Exact URL to match
        timeout: Maximum wait time in seconds

    Returns:
        dict with matched, url, elapsed
    """
    start_time = time.time()

    while True:
        elapsed = time.time() - start_time

        if elapsed > timeout:
            current_url = (
                tab.target.url if hasattr(tab, "target") and tab.target else ""
            )
            return {
                "matched": False,
                "url": current_url,
                "elapsed": round(elapsed, 2),
            }

        current_url = tab.target.url if hasattr(tab, "target") and tab.target else ""

        if exact:
            if current_url == exact:
                return {
                    "matched": True,
                    "url": current_url,
                    "elapsed": round(elapsed, 2),
                }
        elif pattern:
            if pattern in current_url or re.search(pattern, current_url):
                return {
                    "matched": True,
                    "url": current_url,
                    "elapsed": round(elapsed, 2),
                }

        await asyncio.sleep(0.3)
