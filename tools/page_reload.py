#!/usr/bin/env python3
"""Reload the current page, or go back/forward.

Usage:
    python tools/page_reload.py [--port 9222]
    python tools/page_reload.py --back
    python tools/page_reload.py --forward

Output:
    {"action": "reload", "url": "https://example.com"}
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools._common import output, error, add_port_arg, connect_browser, get_active_tab, run_async


async def main_async(args):
    browser = await connect_browser(args.port)
    tab = await get_active_tab(browser)

    if args.back:
        await tab.back()
        action = "back"
    elif args.forward:
        await tab.forward()
        action = "forward"
    else:
        await tab.reload()
        action = "reload"

    await asyncio.sleep(1)

    url = await tab.evaluate("window.location.href")
    title = await tab.evaluate("document.title")

    output({
        "action": action,
        "url": url,
        "title": title
    })


def main():
    parser = argparse.ArgumentParser(description="Reload/back/forward")
    add_port_arg(parser)
    parser.add_argument("--back", "-b", action="store_true", help="Go back")
    parser.add_argument("--forward", "-f", action="store_true", help="Go forward")
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
