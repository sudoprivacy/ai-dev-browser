"""Wait for URL to match a pattern.

CLI:
    python -m nodriver_kit.tools.wait_url --pattern "/dashboard"
    python -m nodriver_kit.tools.wait_url --exact "https://example.com/login"

Python:
    from nodriver_kit.tools import wait_url
    result = await wait_url(tab, pattern="/dashboard")
"""

import asyncio
import re
import time

from ._cli import as_cli


@as_cli
async def wait_url(
    tab,
    pattern: str = None,
    exact: str = None,
    timeout: float = 30,
) -> dict:
    """Wait for URL to match pattern.

    Args:
        tab: Browser tab
        pattern: URL pattern (substring or regex)
        exact: Exact URL to match
        timeout: Maximum wait time in seconds

    Returns:
        {"matched": True, "url": ..., "elapsed": ...}
    """
    if not pattern and not exact:
        return {"error": "Must specify --pattern or --exact"}

    start_time = time.time()

    while True:
        elapsed = time.time() - start_time

        if elapsed > timeout:
            current_url = tab.target.url if hasattr(tab, "target") and tab.target else ""
            return {
                "matched": False,
                "url": current_url,
                "elapsed": round(elapsed, 2),
                "message": f"Timeout after {timeout}s",
            }

        current_url = tab.target.url if hasattr(tab, "target") and tab.target else ""

        if exact:
            if current_url == exact:
                return {
                    "matched": True,
                    "url": current_url,
                    "elapsed": round(elapsed, 2),
                }
        elif pattern:
            if pattern in current_url or re.search(pattern, current_url):
                return {
                    "matched": True,
                    "url": current_url,
                    "elapsed": round(elapsed, 2),
                }

        await asyncio.sleep(0.3)


if __name__ == "__main__":
    wait_url.cli_main()
