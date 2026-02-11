"""Browser connection utilities."""

import logging

import nodriver
from nodriver import cdp

from .config import DEFAULT_DEBUG_HOST, DEFAULT_DEBUG_PORT

logger = logging.getLogger(__name__)


async def connect_browser(
    host: str = DEFAULT_DEBUG_HOST,
    port: int = DEFAULT_DEBUG_PORT,
) -> nodriver.Browser:
    """Connect to existing Chrome instance.

    Args:
        host: Chrome debugging host
        port: Chrome debugging port

    Returns:
        Browser instance

    Raises:
        ConnectionError: If unable to connect
    """
    try:
        # Pass host AND port directly to nodriver.start()
        # When both are provided, nodriver connects to existing browser instead of starting new one
        browser = await nodriver.start(host=host, port=port)

        # Explicitly attach to all page targets via CDP.
        # nodriver connects directly to target WebSocket URLs, bypassing
        # Target.attachToTarget(). This means Chrome doesn't know there's
        # a client attached, and is_chrome_in_use() can't detect it.
        # By calling attachToTarget explicitly, Chrome marks these targets
        # as attached, making in-use detection reliable.
        await _attach_to_page_targets(browser)

        return browser
    except Exception as e:
        raise ConnectionError(
            f"Failed to connect to Chrome on {host}:{port}: {e}"
        ) from e


async def _attach_to_page_targets(browser: nodriver.Browser) -> None:
    """Explicitly attach to page targets so Chrome tracks our connection.

    This makes is_chrome_in_use() work reliably: attached=True while
    connected, attached=False when our process exits (WebSocket closes).
    """
    targets = getattr(browser, "targets", None) or []
    for target in targets:
        if getattr(target, "type_", "") != "page":
            continue
        target_id = getattr(target, "target", None)
        if target_id is None:
            continue
        tid = getattr(target_id, "target_id", None)
        if tid is None:
            continue
        try:
            await browser.connection.send(
                cdp.target.attach_to_target(tid, flatten=True)
            )
            logger.debug(f"Attached to page target {tid}")
        except Exception as e:
            logger.debug(f"Could not attach to target {tid}: {e}")


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
