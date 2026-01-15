#!/usr/bin/env python3
"""List all open browser tabs.

Usage:
    python tools/tab_list.py [--port 9222]

Output:
    {"tabs": [{"id": 0, "url": "...", "title": "...", "active": true}], "count": 3}
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools._common import output, add_port_arg, connect_browser, run_async


async def main_async(args):
    browser = await connect_browser(args.port)

    tabs_info = []
    active_tab = None

    # Find the currently active tab
    for i, tab in enumerate(browser.tabs):
        if hasattr(tab, "target") and tab.target:
            is_active = tab == browser.main_tab
            info = {
                "id": i,
                "url": tab.target.url if tab.target.url else "",
                "title": tab.target.title if tab.target.title else "",
                "active": is_active,
            }
            tabs_info.append(info)
            if is_active:
                active_tab = i

    output({"tabs": tabs_info, "count": len(tabs_info), "active": active_tab})


def main():
    parser = argparse.ArgumentParser(description="List browser tabs")
    add_port_arg(parser)
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
