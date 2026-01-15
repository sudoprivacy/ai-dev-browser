"""Browser connection utilities."""

import nodriver


async def connect_browser(
    host: str = "127.0.0.1",
    port: int = 9222,
) -> nodriver.Browser:
    """Connect to existing Chrome instance.

    Args:
        host: Chrome debugging host (default: 127.0.0.1)
        port: Chrome debugging port (default: 9222)

    Returns:
        Browser instance

    Raises:
        ConnectionError: If unable to connect
    """
    try:
        browser = await nodriver.start(host=host, port=port)
        return browser
    except Exception as e:
        raise ConnectionError(f"Failed to connect to Chrome on {host}:{port}: {e}")


async def get_active_tab(browser: nodriver.Browser) -> nodriver.Tab:
    """Get the active/main tab from browser.

    Args:
        browser: Browser instance

    Returns:
        Active tab, or creates a blank one if none exists
    """
    # Try to find existing tab
    targets = getattr(browser, "targets", None) or []
    page_targets = [t for t in targets if getattr(t, "type_", "") == "page"]

    for target in page_targets:
        url = getattr(target, "url", "") or ""
        if url and not url.startswith("about:"):
            return target

    if page_targets:
        return page_targets[0]

    # No tabs, create one
    return await browser.get("about:blank")
