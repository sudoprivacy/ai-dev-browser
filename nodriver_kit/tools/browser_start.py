"""Start a browser instance.

CLI:
    python -m nodriver_kit.tools.browser_start --port 9222
    python -m nodriver_kit.tools.browser_start --headless

Python:
    from nodriver_kit.tools import browser_start
    result = await browser_start(port=9222)
"""

import argparse
import json
from nodriver_kit.core import launch_chrome, get_available_port


def browser_start(
    port: int = None,
    headless: bool = False,
) -> dict:
    """Start a new browser instance.

    Args:
        port: Debug port (auto-assigned if None)
        headless: Run in headless mode

    Returns:
        {"port": ..., "pid": ..., "headless": ...}
    """
    try:
        if port is None:
            port = get_available_port()

        # Use launch_chrome which starts a subprocess that stays alive
        process = launch_chrome(port=port, headless=headless)

        return {
            "port": port,
            "pid": process.pid,
            "headless": headless,
            "message": f"Browser started on port {port}",
        }
    except Exception as e:
        return {"error": f"Start browser failed: {e}"}


def cli_main():
    parser = argparse.ArgumentParser(description="Start a browser instance")
    parser.add_argument("--port", "-p", type=int, help="Debug port")
    parser.add_argument("--headless", action="store_true", help="Run headless")
    args = parser.parse_args()

    result = browser_start(
        port=args.port,
        headless=args.headless,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    cli_main()
