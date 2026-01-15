#!/usr/bin/env python3
"""Navigate to a URL.

Usage:
    python tools/page_goto.py --url "https://example.com" [--port 9222] [--wait 2]

Output:
    {"url": "https://example.com", "title": "Example Domain"}
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools._common import output, error, add_port_arg, connect_browser, get_active_tab, run_async


async def main_async(args):
    browser = await connect_browser(args.port)
    tab = await get_active_tab(browser)

    await tab.get(args.url)

    if args.wait > 0:
        import asyncio
        await asyncio.sleep(args.wait)

    title = await tab.evaluate("document.title")
    current_url = await tab.evaluate("window.location.href")

    output({
        "url": current_url,
        "title": title,
        "message": f"Navigated to {args.url}"
    })


def main():
    parser = argparse.ArgumentParser(description="Navigate to URL")
    add_port_arg(parser)
    parser.add_argument("--url", "-u", required=True, help="URL to navigate to")
    parser.add_argument("--wait", "-w", type=float, default=2, help="Seconds to wait after navigation (default: 2)")
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
