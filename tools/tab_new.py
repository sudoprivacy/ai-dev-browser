#!/usr/bin/env python3
"""Open a new browser tab.

Usage:
    python tools/tab_new.py --url "https://example.com" [--port 9222]
    python tools/tab_new.py  # Opens blank tab

Output:
    {"id": 2, "url": "https://example.com", "title": "Example Domain"}
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools._common import (
    output,
    add_port_arg,
    connect_browser,
    get_active_tab,
    run_async,
)


async def main_async(args):
    browser = await connect_browser(args.port)
    tab = await get_active_tab(browser)

    url = args.url or "about:blank"

    # Open URL in new tab
    new_tab = await tab.get(url, new_tab=True)

    # Wait a moment for the page to start loading
    await new_tab.sleep(0.5)

    # Get tab info
    tab_id = len(browser.tabs) - 1
    title = ""
    if hasattr(new_tab, "target") and new_tab.target:
        title = new_tab.target.title or ""

    output({"id": tab_id, "url": url, "title": title, "message": "Opened new tab"})


def main():
    parser = argparse.ArgumentParser(description="Open new tab")
    add_port_arg(parser)
    parser.add_argument("--url", "-u", help="URL to open (default: blank)")
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
