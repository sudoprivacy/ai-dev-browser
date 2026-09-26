"""Tab management operations."""

import contextlib

from ai_dev_browser.cdp import target as cdp_target

from ._tab import Tab
from .connection import BrowserClient


def _get_browser(browser_or_tab: BrowserClient | Tab) -> BrowserClient:
    """Extract browser from browser or tab instance."""
    if isinstance(browser_or_tab, Tab):
        return browser_or_tab.browser
    return browser_or_tab


async def tab_new(
    browser_or_tab: BrowserClient | Tab,
    url: str | None = None,
) -> dict:
    """Open a new tab.

    Args:
        browser_or_tab: Browser or Tab instance
        url: URL to open (default: about:blank)

    Returns:
        dict with url, title, tab (for programmatic use)
    """
    url = url or "about:blank"

    if isinstance(browser_or_tab, Tab):
        tab = await browser_or_tab.get(url, tab_new=True)
    else:
        tab = await browser_or_tab.get(url)

    await tab.sleep(0.5)
    title = tab.target.title if tab.target else ""
    return {"url": url, "title": title, "tab": tab}


async def tab_list(browser_or_tab: BrowserClient | Tab) -> dict:
    """List all open tabs.

    Args:
        browser_or_tab: Browser or Tab instance

    Returns:
        dict with tabs list and count
    """
    browser = _get_browser(browser_or_tab)
    tabs_info = []

    for i, tab in enumerate(browser.tabs):
        if hasattr(tab, "target") and tab.target:
            is_active = tab == browser.main_tab
            info = {
                "id": i,
                "url": tab.target.url if tab.target.url else "",
                "title": tab.target.title if tab.target.title else "",
                "active": is_active,
            }
            tabs_info.append(info)

    return {"tabs": tabs_info, "count": len(tabs_info)}


async def tab_switch(
    browser_or_tab: BrowserClient | Tab,
    tab_id: int,
) -> dict:
    """Switch to a different tab.

    Args:
        browser_or_tab: Browser or Tab instance
        tab_id: Tab index to switch to

    Returns:
        dict with url, title, tab (for programmatic use)

    Raises:
        IndexError: If tab_id is invalid
    """
    browser = _get_browser(browser_or_tab)

    if tab_id < 0 or tab_id >= len(browser.tabs):
        raise IndexError(
            f"Invalid tab ID: {tab_id}. Available: 0-{len(browser.tabs) - 1}"
        )

    tab = browser.tabs[tab_id]
    await tab.activate()
    await tab.bring_to_front()
    url = tab.target.url if tab.target else ""
    title = tab.target.title if tab.target else ""
    return {"url": url, "title": title, "tab": tab}


async def tab_close(
    browser_or_tab: BrowserClient | Tab,
    tab_id: int | None = None,
    tab: Tab | None = None,
) -> dict:
    """Close a tab (the real browser tab, both cdp and extension transports).

    Returns `{closed, remaining}` — `closed` reports whether the tab is actually
    gone (re-checked against a fresh target list), `remaining` is the live count
    after closing. `closed: false` means it didn't close (and says why).

    Args:
        browser_or_tab: Browser or Tab instance
        tab_id: Tab index to close (from `tab_list`)
        tab: Tab instance to close

    Returns:
        dict with `closed` and `remaining`.

    Raises:
        ValueError: If trying to close the last tab, or the target can't be
            resolved.

    Failure:
        `closed: false` means the tab is still open after the close — verify the
        `tab_id` against a fresh `tab_list`. (Closing is driven by
        `Target.closeTarget`, which the extension bridge maps to
        `chrome.tabs.remove`, so extension transport is supported.)
    """
    browser = _get_browser(browser_or_tab)

    if len(browser.tabs) <= 1:
        raise ValueError("Cannot close the last tab")

    if tab is None and tab_id is not None:
        tab = browser.tabs[tab_id]
    elif tab is None:
        tab = browser.main_tab

    target_id = getattr(getattr(tab, "_target", None), "target_id", None)
    if target_id is None:
        raise ValueError("Cannot resolve the target to close")

    # Actually close the BROWSER tab via Target.closeTarget (the extension bridge
    # maps it to chrome.tabs.remove), not just drop adb's per-tab WebSocket —
    # `tab.close()` only disconnected the socket, so the tab stayed open and the
    # call looked successful while doing nothing.
    if browser.connection is not None:
        await browser.connection.send(cdp_target.close_target(target_id=target_id))
    with contextlib.suppress(Exception):
        await tab.close()  # drop our now-dead per-tab socket

    # Re-fetch targets so `remaining` is the live count and we can VERIFY the
    # close (the old code returned the pre-close count — a failed close read as
    # success and left the caller acting on a stale/closed tab).
    await browser.update_targets()
    still_open = any(
        getattr(t._target, "target_id", None) == target_id for t in browser.tabs
    )
    remaining = len(browser.tabs)
    if still_open:
        return {
            "closed": False,
            "remaining": remaining,
            "error": f"tab {tab_id} did not close (target {target_id} still present)",
        }
    return {"closed": True, "remaining": remaining}
