"""Tab management operations."""

from typing import Optional

import nodriver


async def new_tab(
    browser_or_tab: nodriver.Browser | nodriver.Tab,
    url: Optional[str] = None,
) -> nodriver.Tab:
    """Open a new tab.

    Args:
        browser_or_tab: Browser or Tab instance
        url: URL to open (default: about:blank)

    Returns:
        New tab instance
    """
    url = url or "about:blank"

    if isinstance(browser_or_tab, nodriver.Tab):
        tab = await browser_or_tab.get(url, new_tab=True)
    else:
        tab = await browser_or_tab.get(url)

    await tab.sleep(0.5)
    return tab


def list_tabs(browser: nodriver.Browser) -> list:
    """List all open tabs.

    Args:
        browser: Browser instance

    Returns:
        List of tab info dicts
    """
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

    return tabs_info


async def switch_tab(browser: nodriver.Browser, tab_id: int) -> nodriver.Tab:
    """Switch to a different tab.

    Args:
        browser: Browser instance
        tab_id: Tab index to switch to

    Returns:
        The activated tab

    Raises:
        IndexError: If tab_id is invalid
    """
    if tab_id < 0 or tab_id >= len(browser.tabs):
        raise IndexError(
            f"Invalid tab ID: {tab_id}. Available: 0-{len(browser.tabs) - 1}"
        )

    tab = browser.tabs[tab_id]
    await tab.activate()
    await tab.bring_to_front()
    return tab


async def close_tab(
    browser: nodriver.Browser,
    tab_id: Optional[int] = None,
    tab: Optional[nodriver.Tab] = None,
) -> int:
    """Close a tab.

    Args:
        browser: Browser instance
        tab_id: Tab index to close
        tab: Tab instance to close

    Returns:
        Number of remaining tabs

    Raises:
        ValueError: If trying to close the last tab
    """
    if len(browser.tabs) <= 1:
        raise ValueError("Cannot close the last tab")

    if tab is None and tab_id is not None:
        tab = browser.tabs[tab_id]
    elif tab is None:
        tab = browser.main_tab

    await tab.close()
    return len(browser.tabs)
