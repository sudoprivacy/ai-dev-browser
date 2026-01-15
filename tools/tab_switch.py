#!/usr/bin/env python3
"""Switch to a different browser tab.

Usage:
    python tools/tab_switch.py --id 0 [--port 9222]
    python tools/tab_switch.py --id 2

Output:
    {"id": 2, "url": "...", "title": "...", "message": "Switched to tab 2"}
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools._common import output, error, add_port_arg, connect_browser, run_async


async def main_async(args):
    browser = await connect_browser(args.port)

    tab_id = args.id

    if tab_id < 0 or tab_id >= len(browser.tabs):
        error(f"Invalid tab ID: {tab_id}. Available: 0-{len(browser.tabs) - 1}")

    tab = browser.tabs[tab_id]

    # Activate the tab
    await tab.activate()
    await tab.bring_to_front()

    # Get tab info
    url = tab.target.url if hasattr(tab, "target") and tab.target else ""
    title = tab.target.title if hasattr(tab, "target") and tab.target else ""

    output(
        {
            "id": tab_id,
            "url": url,
            "title": title,
            "message": f"Switched to tab {tab_id}",
        }
    )


def main():
    parser = argparse.ArgumentParser(description="Switch to tab")
    add_port_arg(parser)
    parser.add_argument(
        "--id", "-i", type=int, required=True, help="Tab ID to switch to"
    )
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
