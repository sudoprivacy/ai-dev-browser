"""Start a browser instance.

CLI:
    python -m nodriver_kit.tools.browser_start --port 9222
    python -m nodriver_kit.tools.browser_start --url "https://example.com"
    python -m nodriver_kit.tools.browser_start --headless

Python:
    from nodriver_kit.tools import browser_start
    result = browser_start(port=9222, url="https://example.com")
"""

import argparse
import json
from nodriver_kit.core import launch_chrome, get_available_port


def browser_start(
    port: int = None,
    headless: bool = False,
    url: str = None,
) -> dict:
    """Start a new browser instance.

    Args:
        port: Debug port (auto-assigned if None)
        headless: Run in headless mode
        url: Initial URL to open (default: about:blank)

    Returns:
        {"port": ..., "pid": ..., "headless": ..., "url": ...}
    """
    try:
        if port is None:
            port = get_available_port()

        # Use launch_chrome which starts a subprocess that stays alive
        start_url = url or "about:blank"
        process = launch_chrome(port=port, headless=headless, start_url=start_url)

        return {
            "port": port,
            "pid": process.pid,
            "headless": headless,
            "url": start_url,
            "message": f"Browser started on port {port}",
        }
    except Exception as e:
        return {"error": f"Start browser failed: {e}"}


def cli_main():
    parser = argparse.ArgumentParser(description="Start a browser instance")
    parser.add_argument("--port", "-p", type=int, help="Debug port")
    parser.add_argument("--url", "-u", help="Initial URL to open")
    parser.add_argument("--headless", action="store_true", help="Run headless")
    args = parser.parse_args()

    result = browser_start(
        port=args.port,
        headless=args.headless,
        url=args.url,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    cli_main()
