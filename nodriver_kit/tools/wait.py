"""Wait for element or condition.

CLI:
    python -m nodriver_kit.tools.wait --text "Success"
    python -m nodriver_kit.tools.wait --selector ".loaded"
    python -m nodriver_kit.tools.wait --url "https://example.com/done"

Python:
    from nodriver_kit.tools import wait
    result = await wait(tab, text="Success")
"""

from nodriver_kit.core import wait_for_element, wait_for_url
from ._cli import as_cli


@as_cli
async def wait(
    tab,
    text: str = None,
    selector: str = None,
    url: str = None,
    timeout: float = 30,
) -> dict:
    """Wait for element or URL.

    Args:
        tab: Browser tab
        text: Text to wait for
        selector: CSS selector to wait for
        url: URL pattern to wait for
        timeout: Maximum wait time in seconds

    Returns:
        {"found": True, "elapsed": ...} on success
    """
    if not text and not selector and not url:
        return {"error": "Must specify --text, --selector, or --url"}

    try:
        if url:
            result = await wait_for_url(tab, url, timeout=timeout)
        else:
            result = await wait_for_element(tab, text=text, selector=selector, timeout=timeout)
        return result
    except Exception as e:
        return {"error": f"Wait failed: {e}"}


if __name__ == "__main__":
    wait.cli_main()
