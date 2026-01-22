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

from ..core.navigation import wait_for_load as core_wait_for_load
from ._cli import as_cli


@as_cli()
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
        # Use core function for the wait loop
        ready = await core_wait_for_load(tab, timeout=timeout, idle_time=0.5)
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
    ready = await core_wait_for_load(tab, timeout=10, idle_time=0)
    state = await tab.evaluate("document.readyState")

    return {
        "ready": ready,
        "state": state,
    }


if __name__ == "__main__":
    page_wait.cli_main()
