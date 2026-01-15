#!/usr/bin/env python3
"""Type text into an input element.

Usage:
    python tools/element_type.py --selector "input[name=email]" --text "user@example.com" [--port 9222]
    python tools/element_type.py --selector "input[name=email]" --text "user@example.com" --clear [--port 9222]

Output:
    {"typed": true, "message": "Typed text into element"}
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools._common import output, error, add_port_arg, connect_browser, get_active_tab, run_async


async def main_async(args):
    browser = await connect_browser(args.port)
    tab = await get_active_tab(browser)

    try:
        element = await tab.select(args.selector)
    except Exception as e:
        error(f"Element with selector '{args.selector}' not found: {e}")

    if not element:
        error("Element not found")

    try:
        await element.scroll_into_view()
        await asyncio.sleep(0.2)

        # Click to focus
        await element.mouse_click()
        await asyncio.sleep(0.1)

        # Clear existing content if requested
        if args.clear:
            await element.clear_input()
            await asyncio.sleep(0.1)

        # Type text
        await element.send_keys(args.text)

        output({
            "typed": True,
            "text": args.text,
            "message": f"Typed text into element"
        })
    except Exception as e:
        error(f"Type failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Type into input")
    add_port_arg(parser)
    parser.add_argument("--selector", "-s", required=True, help="CSS selector for input")
    parser.add_argument("--text", "-t", required=True, help="Text to type")
    parser.add_argument("--clear", "-c", action="store_true", help="Clear existing content first")
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
