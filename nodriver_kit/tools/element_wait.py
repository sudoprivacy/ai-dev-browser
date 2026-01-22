"""Wait for an element to appear.

CLI:
    python -m nodriver_kit.tools.element_wait --text "Success"
    python -m nodriver_kit.tools.element_wait --selector ".loaded"

Python:
    from nodriver_kit.tools import element_wait
    result = await element_wait(tab, text="Success")
"""

from ..core.elements import wait_for_element as core_wait_for_element
from ._cli import as_cli


@as_cli()
async def element_wait(
    tab,
    text: str = None,
    selector: str = None,
    timeout: float = 30,
) -> dict:
    """Wait for element to appear.

    Args:
        tab: Browser tab
        text: Text to wait for
        selector: CSS selector to wait for
        timeout: Maximum wait time in seconds

    Returns:
        {"found": True, "elapsed": ...}
    """
    if not text and not selector:
        return {"error": "Must specify --text or --selector"}

    result = await core_wait_for_element(tab, text=text, selector=selector, timeout=timeout)

    # Add descriptive message
    if result.get("found"):
        if text:
            result["message"] = f"Element with text '{text}' found"
        else:
            result["message"] = f"Element '{selector}' found"
    else:
        result["message"] = f"Timeout after {timeout}s"

    return result


if __name__ == "__main__":
    element_wait.cli_main()
