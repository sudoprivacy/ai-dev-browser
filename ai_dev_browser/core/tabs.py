"""Tab management operations."""

from ._tab import Tab
from .connection import BrowserClient


def _get_browser(browser_or_tab: BrowserClient | Tab) -> BrowserClient:
    """Extract browser from browser or tab instance."""
    if isinstance(browser_or_tab, Tab):
        return browser_or_tab.browser
    return browser_or_tab


async def new_tab(
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
        tab = await browser_or_tab.get(url, new_tab=True)
    else:
        tab = await browser_or_tab.get(url)

    await tab.sleep(0.5)
    title = tab.target.title if tab.target else ""
    return {"url": url, "title": title, "tab": tab}


async def list_tabs(browser_or_tab: BrowserClient | Tab) -> dict:
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


async def switch_tab(
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


async def close_tab(
    browser_or_tab: BrowserClient | Tab,
    tab_id: int | None = None,
    tab: Tab | None = None,
) -> dict:
    """Close a tab.

    Args:
        browser_or_tab: Browser or Tab instance
        tab_id: Tab index to close
        tab: Tab instance to close

    Returns:
        dict with remaining tab count

    Raises:
        ValueError: If trying to close the last tab
    """
    browser = _get_browser(browser_or_tab)

    if len(browser.tabs) <= 1:
        raise ValueError("Cannot close the last tab")

    if tab is None and tab_id is not None:
        tab = browser.tabs[tab_id]
    elif tab is None:
        tab = browser.main_tab

    await tab.close()
    return {"remaining": len(browser.tabs)}
