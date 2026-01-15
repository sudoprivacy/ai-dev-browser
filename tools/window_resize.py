#!/usr/bin/env python3
"""Resize browser window.

Usage:
    python tools/window_resize.py --width 1920 --height 1080
    python tools/window_resize.py --width 375 --height 812  # iPhone size

Output:
    {"width": 1920, "height": 1080, "message": "Window resized to 1920x1080"}
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
        await tab.set_window_size(
            left=args.left, top=args.top, width=args.width, height=args.height
        )

        output(
            {
                "width": args.width,
                "height": args.height,
                "left": args.left,
                "top": args.top,
                "message": f"Window resized to {args.width}x{args.height}",
            }
        )

    except Exception as e:
        error(f"Window resize failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Resize window")
    add_port_arg(parser)
    parser.add_argument(
        "--width", "-w", type=int, default=1280, help="Window width (default: 1280)"
    )
    parser.add_argument(
        "--height", "-h", type=int, default=720, help="Window height (default: 720)"
    )
    parser.add_argument(
        "--left", "-l", type=int, default=0, help="Window left position (default: 0)"
    )
    parser.add_argument(
        "--top", "-t", type=int, default=0, help="Window top position (default: 0)"
    )
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
