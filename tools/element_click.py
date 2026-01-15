#!/usr/bin/env python3
"""Click an element on the page.

Usage:
    python tools/element_click.py --text "Login" [--port 9222]
    python tools/element_click.py --selector "button.submit" [--port 9222]

Output:
    {"clicked": true, "message": "Clicked element"}
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

    element = None

    if args.text:
        try:
            element = await tab.find(args.text, best_match=True)
        except Exception as e:
            error(f"Element with text '{args.text}' not found: {e}")

    elif args.selector:
        try:
            element = await tab.select(args.selector)
        except Exception as e:
            error(f"Element with selector '{args.selector}' not found: {e}")

    if not element:
        error("Element not found")

    try:
        await element.scroll_into_view()
        await asyncio.sleep(0.3)
        await element.mouse_click()

        output({
            "clicked": True,
            "message": f"Clicked element"
        })
    except Exception as e:
        error(f"Click failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Click element")
    add_port_arg(parser)
    parser.add_argument("--text", "-t", help="Find by text content")
    parser.add_argument("--selector", "-s", help="Find by CSS selector")
    args = parser.parse_args()

    if not args.text and not args.selector:
        error("Must specify --text or --selector")

    run_async(main_async(args))


if __name__ == "__main__":
    main()
