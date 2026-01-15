#!/usr/bin/env python3
"""Move mouse to coordinates.

Usage:
    python tools/mouse_move.py --x 100 --y 200
    python tools/mouse_move.py --x 500 --y 300 --steps 20

Output:
    {"x": 100, "y": 200, "message": "Mouse moved to (100, 200)"}
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
        await tab.mouse_move(args.x, args.y, steps=args.steps)

        output(
            {
                "x": args.x,
                "y": args.y,
                "message": f"Mouse moved to ({args.x}, {args.y})",
            }
        )

    except Exception as e:
        error(f"Mouse move failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Move mouse")
    add_port_arg(parser)
    parser.add_argument("--x", type=float, required=True, help="X coordinate")
    parser.add_argument("--y", type=float, required=True, help="Y coordinate")
    parser.add_argument(
        "--steps", type=int, default=10, help="Steps for smooth movement (default: 10)"
    )
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
