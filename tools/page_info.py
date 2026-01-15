#!/usr/bin/env python3
"""Get current page info (URL, title, etc.).

Usage:
    python tools/page_info.py [--port 9222]

Output:
    {"url": "https://example.com", "title": "Example Domain", "ready": true}
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

    # Get URL and title
    url = tab.target.url if hasattr(tab, "target") and tab.target else ""
    title = tab.target.title if hasattr(tab, "target") and tab.target else ""

    # Get ready state
    try:
        state = await tab.evaluate("document.readyState")
    except Exception:
        state = "unknown"

    output({"url": url, "title": title, "ready": state == "complete", "state": state})


def main():
    parser = argparse.ArgumentParser(description="Get page info")
    add_port_arg(parser)
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
