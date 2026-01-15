#!/usr/bin/env python3
"""Close a browser tab.

Usage:
    python tools/tab_close.py [--port 9222]           # Close current tab
    python tools/tab_close.py --id 2 [--port 9222]   # Close specific tab

Output:
    {"closed": 2, "remaining": 2, "message": "Closed tab 2"}
"""

import argparse
import sys
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

    if args.id is not None:
        tab_id = args.id
        if tab_id < 0 or tab_id >= len(browser.tabs):
            error(f"Invalid tab ID: {tab_id}. Available: 0-{len(browser.tabs) - 1}")
        tab = browser.tabs[tab_id]
    else:
        tab = await get_active_tab(browser)
        # Find the tab ID
        tab_id = browser.tabs.index(tab) if tab in browser.tabs else -1

    if len(browser.tabs) <= 1:
        error("Cannot close the last tab. Use browser_stop to close the browser.")

    # Close the tab
    await tab.close()

    output(
        {
            "closed": tab_id,
            "remaining": len(browser.tabs),
            "message": f"Closed tab {tab_id}",
        }
    )


def main():
    parser = argparse.ArgumentParser(description="Close tab")
    add_port_arg(parser)
    parser.add_argument(
        "--id", "-i", type=int, help="Tab ID to close (default: current tab)"
    )
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
