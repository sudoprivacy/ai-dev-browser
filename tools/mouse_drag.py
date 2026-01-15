#!/usr/bin/env python3
"""Drag from one point to another.

Usage:
    python tools/mouse_drag.py --from-x 100 --from-y 200 --to-x 300 --to-y 400
    python tools/mouse_drag.py --from-x 100 --from-y 200 --to-x 300 --to-y 400 --steps 20

Output:
    {"from": [100, 200], "to": [300, 400], "message": "Dragged from (100, 200) to (300, 400)"}
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
        await tab.mouse_drag(
            (args.from_x, args.from_y), (args.to_x, args.to_y), steps=args.steps
        )

        output(
            {
                "from": [args.from_x, args.from_y],
                "to": [args.to_x, args.to_y],
                "message": f"Dragged from ({args.from_x}, {args.from_y}) to ({args.to_x}, {args.to_y})",
            }
        )

    except Exception as e:
        error(f"Mouse drag failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Drag mouse")
    add_port_arg(parser)
    parser.add_argument(
        "--from-x", type=float, required=True, help="Start X coordinate"
    )
    parser.add_argument(
        "--from-y", type=float, required=True, help="Start Y coordinate"
    )
    parser.add_argument("--to-x", type=float, required=True, help="End X coordinate")
    parser.add_argument("--to-y", type=float, required=True, help="End Y coordinate")
    parser.add_argument(
        "--steps", type=int, default=10, help="Steps for smooth drag (default: 10)"
    )
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
