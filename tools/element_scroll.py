#!/usr/bin/env python3
"""Scroll on the page.

Usage:
    python tools/element_scroll.py --to "Login"           # Scroll to element by text
    python tools/element_scroll.py --selector "#footer"   # Scroll to element by selector
    python tools/element_scroll.py --y 500                # Scroll down 500px
    python tools/element_scroll.py --top                  # Scroll to top
    python tools/element_scroll.py --bottom               # Scroll to bottom

Output:
    {"scrolled": true, "message": "Scrolled to element"}
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

    if args.to:
        # Scroll to element by text
        try:
            element = await tab.find(args.to, best_match=True)
            await element.scroll_into_view()
            output({"scrolled": True, "message": f"Scrolled to element with text '{args.to}'"})
        except Exception as e:
            error(f"Element not found: {e}")

    elif args.selector:
        # Scroll to element by selector
        try:
            element = await tab.select(args.selector)
            await element.scroll_into_view()
            output({"scrolled": True, "message": f"Scrolled to element '{args.selector}'"})
        except Exception as e:
            error(f"Element not found: {e}")

    elif args.top:
        await tab.evaluate("window.scrollTo(0, 0)")
        output({"scrolled": True, "message": "Scrolled to top"})

    elif args.bottom:
        await tab.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        output({"scrolled": True, "message": "Scrolled to bottom"})

    elif args.y is not None:
        await tab.evaluate(f"window.scrollBy(0, {args.y})")
        output({"scrolled": True, "message": f"Scrolled by {args.y}px"})

    else:
        error("Must specify --to, --selector, --y, --top, or --bottom")


def main():
    parser = argparse.ArgumentParser(description="Scroll on page")
    add_port_arg(parser)
    parser.add_argument("--to", "-t", help="Scroll to element by text")
    parser.add_argument("--selector", "-s", help="Scroll to element by CSS selector")
    parser.add_argument("--y", type=int, help="Scroll by Y pixels (positive=down)")
    parser.add_argument("--top", action="store_true", help="Scroll to top")
    parser.add_argument("--bottom", action="store_true", help="Scroll to bottom")
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
