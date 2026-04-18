"""Page navigation operations."""

import asyncio
import re
import time

from ._tab import Tab


async def page_goto(
    tab: Tab,
    url: str,
    tab_new: bool = False,
    wait: bool = True,
) -> dict:
    """Use when: you want to load a specific URL (first navigation, jumping
    directly to a page, opening in a new tab). Returns `{url, title,
    success}` — next step is typically `page_discover` or a targeted
    `click_by_*` / `find_by_*`.

    Args:
        tab: Tab instance
        url: URL to navigate to
        tab_new: If True, open in new tab
        wait: If True, wait for page load

    Returns:
        dict with url, title, success
    """
    result_tab = await tab.get(url, tab_new=tab_new)

    if wait:
        await page_wait_ready(result_tab)

    try:
        title = await result_tab.evaluate("document.title")
    except Exception:
        title = ""

    return {
        "url": result_tab.target.url if result_tab.target else url,
        "title": title,
        "success": True,
    }


async def _back(tab: Tab) -> bool:
    """Go back in history."""
    await tab.back()
    return True


async def _forward(tab: Tab) -> bool:
    """Go forward in history."""
    await tab.forward()
    return True


async def page_reload(tab: Tab, ignore_cache: bool = True) -> bool:
    """Use when: page got into a bad state and you want a fresh render, or
    you need to re-trigger the page's initial data load. Returns `True`
    on success. Typically followed by `page_wait_ready` + `page_discover`.

    Args:
        tab: Tab instance
        ignore_cache: If True, ignore browser cache

    Returns:
        True on success
    """
    await tab.reload(ignore_cache=ignore_cache)
    return True


async def page_wait_ready(
    tab: Tab,
    timeout: float = 30,
    idle_time: float = 0.5,
) -> bool:
    """Use when: you kicked off a navigation / action and need to block
    until `document.readyState === "complete"` before reading DOM or
    acting further. Returns `True` on load, `False` on timeout. Typical
    next step is `page_discover` or a targeted locator.

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


async def page_wait_url(
    tab: Tab,
    pattern: str | None = None,
    exact: str | None = None,
    timeout: float = 30,
) -> dict:
    """Use when: you triggered a navigation (click, form submit) and need
    to block until the URL matches — common in OAuth / redirect /
    multi-step SPA flows. Returns `{matched, url, elapsed}`.

    If you only need "did the click cause ANY navigation?", the click_*
    tools now return `navigated` / `url_after` directly — no need for
    this wait.

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
        elif pattern and (pattern in current_url or re.search(pattern, current_url)):
            return {
                "matched": True,
                "url": current_url,
                "elapsed": round(elapsed, 2),
            }

        await asyncio.sleep(0.3)


async def _wait_for_url_match(
    tab: Tab,
    pattern: str | None = None,
    exact: str | None = None,
    timeout: float = 30,
) -> dict:
    """Wait for URL to match pattern with descriptive message.

    Args:
        tab: Tab instance
        pattern: URL pattern (substring or regex)
        exact: Exact URL to match
        timeout: Maximum wait time in seconds

    Returns:
        dict with matched, url, elapsed, message
    """
    if not pattern and not exact:
        return {"error": "Must specify pattern or exact"}

    result = await page_wait_url(tab, pattern=pattern, exact=exact, timeout=timeout)

    # Add timeout message if not matched
    if not result.get("matched"):
        result["message"] = f"Timeout after {timeout}s"

    return result


async def _wait_for_page(
    tab: Tab,
    idle: bool = False,
    sleep: float | None = None,
    timeout: float = 30,
) -> dict:
    """Wait for page to be ready.

    Args:
        tab: Tab instance
        idle: Wait for network idle (document.readyState == complete)
        sleep: Just sleep for N seconds
        timeout: Maximum wait time in seconds

    Returns:
        dict with ready status, state, elapsed, message
    """
    if sleep:
        await asyncio.sleep(sleep)
        return {"ready": True, "message": f"Waited {sleep} seconds"}

    if idle:
        start = time.time()
        ready = await page_wait_ready(tab, timeout=timeout, idle_time=0.5)
        elapsed = time.time() - start

        if ready:
            state = await tab.evaluate("document.readyState")
            return {
                "ready": True,
                "state": state,
                "elapsed": round(elapsed, 2),
            }
        return {
            "ready": False,
            "message": f"Timeout after {timeout}s",
        }

    # Default: quick wait for DOM ready (10s max)
    ready = await page_wait_ready(tab, timeout=10, idle_time=0)
    state = await tab.evaluate("document.readyState")

    return {
        "ready": ready,
        "state": state,
    }
