"""Wait for an element to appear.

CLI:
    python -m nodriver_kit.tools.element_wait --text "Success"
    python -m nodriver_kit.tools.element_wait --selector ".loaded"

Python:
    from nodriver_kit.tools import element_wait
    result = await element_wait(tab, text="Success")
"""

import asyncio
import time

from ._cli import as_cli


@as_cli
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

    start_time = time.time()

    while True:
        elapsed = time.time() - start_time

        if elapsed > timeout:
            return {
                "found": False,
                "elapsed": round(elapsed, 2),
                "message": f"Timeout after {timeout}s",
            }

        try:
            if text:
                element = await tab.find(text, timeout=1)
                if element:
                    return {
                        "found": True,
                        "elapsed": round(elapsed, 2),
                        "message": f"Element with text '{text}' found",
                    }
            elif selector:
                js_code = f"document.querySelector({repr(selector)}) !== null"
                found = await tab.evaluate(js_code)
                if found:
                    return {
                        "found": True,
                        "elapsed": round(elapsed, 2),
                        "message": f"Element '{selector}' found",
                    }
        except Exception:
            pass

        await asyncio.sleep(0.5)


if __name__ == "__main__":
    element_wait.cli_main()
