#!/usr/bin/env python3
"""Wait for URL to match a pattern.

Useful for SPAs where navigation doesn't trigger page load.

Usage:
    python tools/wait_url.py --pattern "/dashboard" [--port 9222]
    python tools/wait_url.py --pattern "example.com" --timeout 30
    python tools/wait_url.py --exact "https://example.com/login"

Output:
    {"matched": true, "url": "https://example.com/dashboard", "elapsed": 2.5}
"""

import argparse
import asyncio
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools._common import (
    output,
    error,
    add_port_arg,
    connect_browser,
    get_active_tab,
    run_async,
)


async def main_async(args):
    browser = await connect_browser(args.port)
    tab = await get_active_tab(browser)

    pattern = args.pattern
    exact = args.exact
    timeout = args.timeout
    start_time = time.time()

    while True:
        elapsed = time.time() - start_time

        if elapsed > timeout:
            current_url = (
                tab.target.url if hasattr(tab, "target") and tab.target else ""
            )
            output(
                {
                    "matched": False,
                    "url": current_url,
                    "elapsed": round(elapsed, 2),
                    "message": f"Timeout after {timeout}s",
                }
            )
            return

        current_url = tab.target.url if hasattr(tab, "target") and tab.target else ""

        if exact:
            if current_url == exact:
                output(
                    {
                        "matched": True,
                        "url": current_url,
                        "elapsed": round(elapsed, 2),
                        "message": "URL matched exactly",
                    }
                )
                return
        elif pattern:
            if pattern in current_url or re.search(pattern, current_url):
                output(
                    {
                        "matched": True,
                        "url": current_url,
                        "elapsed": round(elapsed, 2),
                        "message": f"URL matched pattern '{pattern}'",
                    }
                )
                return

        await asyncio.sleep(0.3)


def main():
    parser = argparse.ArgumentParser(description="Wait for URL pattern")
    add_port_arg(parser)
    parser.add_argument("--pattern", help="URL pattern to match (substring or regex)")
    parser.add_argument("--exact", "-e", help="Exact URL to match")
    parser.add_argument(
        "--timeout",
        "-t",
        type=float,
        default=30,
        help="Timeout in seconds (default: 30)",
    )
    args = parser.parse_args()

    if not args.pattern and not args.exact:
        error("Must specify --pattern or --exact")

    run_async(main_async(args))


if __name__ == "__main__":
    main()
