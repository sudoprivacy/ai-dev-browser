#!/usr/bin/env python3
"""Wait for an element to appear on the page.

Usage:
    python tools/element_wait.py --text "Success" [--timeout 30]
    python tools/element_wait.py --selector ".loading-complete" [--timeout 30]

Output:
    {"found": true, "elapsed": 2.5, "message": "Element found"}
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools._common import output, error, add_port_arg, connect_browser, get_active_tab, run_async


async def main_async(args):
    browser = await connect_browser(args.port)
    tab = await get_active_tab(browser)

    start_time = time.time()
    timeout = args.timeout

    while True:
        elapsed = time.time() - start_time

        if elapsed > timeout:
            output({
                "found": False,
                "elapsed": round(elapsed, 2),
                "message": f"Timeout after {timeout}s"
            })
            return

        try:
            if args.text:
                element = await tab.find(args.text)
                if element:
                    output({
                        "found": True,
                        "elapsed": round(elapsed, 2),
                        "message": f"Element with text '{args.text}' found"
                    })
                    return

            elif args.selector:
                js_code = f"document.querySelector({repr(args.selector)}) !== null"
                found = await tab.evaluate(js_code)
                if found:
                    output({
                        "found": True,
                        "elapsed": round(elapsed, 2),
                        "message": f"Element '{args.selector}' found"
                    })
                    return

        except Exception:
            pass

        await asyncio.sleep(0.5)


def main():
    parser = argparse.ArgumentParser(description="Wait for element")
    add_port_arg(parser)
    parser.add_argument("--text", "-t", help="Wait for element with text")
    parser.add_argument("--selector", "-s", help="Wait for element with CSS selector")
    parser.add_argument("--timeout", type=float, default=30, help="Timeout in seconds (default: 30)")
    args = parser.parse_args()

    if not args.text and not args.selector:
        error("Must specify --text or --selector")

    run_async(main_async(args))


if __name__ == "__main__":
    main()
