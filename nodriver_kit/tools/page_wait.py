"""Wait for page to be ready.

CLI:
    python -m nodriver_kit.tools.page_wait
    python -m nodriver_kit.tools.page_wait --idle
    python -m nodriver_kit.tools.page_wait --sleep 3

Python:
    from nodriver_kit.tools import page_wait
    result = await page_wait(tab, idle=True)
"""

import asyncio
import time

from ._cli import as_cli


@as_cli
async def page_wait(
    tab,
    idle: bool = False,
    sleep: float = None,
    timeout: float = 30,
) -> dict:
    """Wait for page to be ready.

    Args:
        tab: Browser tab
        idle: Wait for network idle (document.readyState == complete)
        sleep: Just sleep for N seconds
        timeout: Maximum wait time in seconds

    Returns:
        {"ready": True, "state": ...}
    """
    if sleep:
        await asyncio.sleep(sleep)
        return {"ready": True, "message": f"Waited {sleep} seconds"}

    if idle:
        start = time.time()

        while time.time() - start < timeout:
            state = await tab.evaluate("document.readyState")
            if state == "complete":
                await asyncio.sleep(0.5)  # Extra wait for pending XHR/fetch
                return {
                    "ready": True,
                    "state": state,
                    "elapsed": round(time.time() - start, 2),
                }
            await asyncio.sleep(0.2)

        return {
            "ready": False,
            "message": f"Timeout after {timeout}s",
        }

    # Default: wait for DOM ready
    state = await tab.evaluate("document.readyState")
    if state != "complete":
        start = time.time()
        while time.time() - start < 10:
            state = await tab.evaluate("document.readyState")
            if state == "complete":
                break
            await asyncio.sleep(0.2)

    return {
        "ready": state == "complete",
        "state": state,
    }


if __name__ == "__main__":
    page_wait.cli_main()
