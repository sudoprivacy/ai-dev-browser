"""Start a browser instance.

CLI:
    python -m nodriver_kit.tools.browser_start --url "https://example.com"
    python -m nodriver_kit.tools.browser_start --profile chatgpt --url "https://chatgpt.com"
    python -m nodriver_kit.tools.browser_start --temp --url "https://example.com"
    python -m nodriver_kit.tools.browser_start --headless

Python:
    from nodriver_kit.tools import browser_start
    result = browser_start(url="https://example.com")  # uses default profile
    result = browser_start(profile="chatgpt", url="https://chatgpt.com")
    result = browser_start(temp=True, url="https://example.com")  # temp profile
"""

import argparse
import json
from pathlib import Path
from nodriver_kit.core import launch_chrome, get_available_port

DEFAULT_PROFILE_DIR = Path.home() / ".nodriver-kit" / "profiles"


def browser_start(
    port: int = None,
    headless: bool = False,
    url: str = None,
    profile: str = None,
    temp: bool = False,
) -> dict:
    """Start a new browser instance.

    Args:
        port: Debug port (auto-assigned if None)
        headless: Run in headless mode
        url: Initial URL to open (default: about:blank)
        profile: Profile name (default: "default", stored in ~/.nodriver-kit/profiles/)
        temp: Use temporary profile instead (clean, no persistence)

    Returns:
        {"port": ..., "pid": ..., "headless": ..., "url": ..., "profile": ...}
    """
    try:
        if port is None:
            port = get_available_port()

        # Determine user data directory
        if temp:
            user_data_dir = None  # launch_chrome will create temp dir
            profile_name = "(temp)"
        else:
            profile_name = profile or "default"
            user_data_dir = DEFAULT_PROFILE_DIR / profile_name
            user_data_dir.mkdir(parents=True, exist_ok=True)

        # Use launch_chrome which starts a subprocess that stays alive
        start_url = url or "about:blank"
        process = launch_chrome(
            port=port,
            headless=headless,
            start_url=start_url,
            user_data_dir=str(user_data_dir) if user_data_dir else None,
        )

        return {
            "port": port,
            "pid": process.pid,
            "headless": headless,
            "url": start_url,
            "profile": profile_name,
            "message": f"Browser started on port {port}",
        }
    except Exception as e:
        return {"error": f"Start browser failed: {e}"}


def cli_main():
    parser = argparse.ArgumentParser(description="Start a browser instance")
    parser.add_argument("--port", "-p", type=int, help="Debug port")
    parser.add_argument("--url", "-u", help="Initial URL to open")
    parser.add_argument("--profile", help="Profile name (default: 'default')")
    parser.add_argument("--temp", action="store_true", help="Use temp profile (no persistence)")
    parser.add_argument("--headless", action="store_true", help="Run headless")
    args = parser.parse_args()

    result = browser_start(
        port=args.port,
        headless=args.headless,
        url=args.url,
        profile=args.profile,
        temp=args.temp,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    cli_main()
