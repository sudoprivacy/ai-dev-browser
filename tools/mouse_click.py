#!/usr/bin/env python3
"""Click at specific coordinates.

Usage:
    python tools/mouse_click.py --x 100 --y 200
    python tools/mouse_click.py --x 500 --y 300 --button right
    python tools/mouse_click.py --x 100 --y 200 --double

Output:
    {"x": 100, "y": 200, "button": "left", "message": "Clicked at (100, 200)"}
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
        # Move to position first
        await tab.mouse_move(args.x, args.y)

        # Click
        await tab.mouse_click(args.x, args.y, button=args.button)

        if args.double:
            await tab.mouse_click(args.x, args.y, button=args.button)

        output(
            {
                "x": args.x,
                "y": args.y,
                "button": args.button,
                "double": args.double,
                "message": f"{'Double c' if args.double else 'C'}licked at ({args.x}, {args.y})",
            }
        )

    except Exception as e:
        error(f"Mouse click failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Click at coordinates")
    add_port_arg(parser)
    parser.add_argument("--x", type=float, required=True, help="X coordinate")
    parser.add_argument("--y", type=float, required=True, help="Y coordinate")
    parser.add_argument(
        "--button",
        "-b",
        choices=["left", "right", "middle"],
        default="left",
        help="Mouse button (default: left)",
    )
    parser.add_argument("--double", "-d", action="store_true", help="Double click")
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
