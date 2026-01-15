#!/usr/bin/env python3
"""Set window state (maximize, minimize, fullscreen).

Usage:
    python tools/window_state.py --maximize
    python tools/window_state.py --minimize
    python tools/window_state.py --fullscreen
    python tools/window_state.py --normal

Output:
    {"state": "maximized", "message": "Window maximized"}
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
    tab = await get_active_tab(browser)

    try:
        if args.maximize:
            await tab.maximize()
            state = "maximized"
        elif args.minimize:
            await tab.minimize()
            state = "minimized"
        elif args.fullscreen:
            await tab.fullscreen()
            state = "fullscreen"
        else:
            await tab.medimize()  # Normal/restored state
            state = "normal"

        output({"state": state, "message": f"Window {state}"})

    except Exception as e:
        error(f"Window state change failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Set window state")
    add_port_arg(parser)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--maximize", action="store_true", help="Maximize window")
    group.add_argument("--minimize", action="store_true", help="Minimize window")
    group.add_argument("--fullscreen", action="store_true", help="Fullscreen window")
    group.add_argument("--normal", action="store_true", help="Restore to normal size")
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
