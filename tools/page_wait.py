#!/usr/bin/env python3
"""Wait for page to be ready.

Usage:
    python tools/page_wait.py [--port 9222]                    # Wait for DOM ready
    python tools/page_wait.py --idle [--timeout 10]            # Wait for network idle
    python tools/page_wait.py --sleep 3                        # Just sleep 3 seconds

Output:
    {"ready": true, "message": "Page ready"}
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

    if args.sleep:
        await asyncio.sleep(args.sleep)
        output({"ready": True, "message": f"Waited {args.sleep} seconds"})
        return

    if args.idle:
        # Wait for network to be idle (no requests for 500ms)
        start = time.time()
        timeout = args.timeout

        while time.time() - start < timeout:
            # Check document.readyState
            state = await tab.evaluate("document.readyState")
            if state == "complete":
                # Additional wait for any pending XHR/fetch
                await asyncio.sleep(0.5)
                output({
                    "ready": True,
                    "state": state,
                    "elapsed": round(time.time() - start, 2),
                    "message": "Page loaded and idle"
                })
                return
            await asyncio.sleep(0.2)

        output({
            "ready": False,
            "message": f"Timeout after {timeout}s"
        })
        return

    # Default: wait for DOM ready
    state = await tab.evaluate("document.readyState")
    if state != "complete":
        # Wait up to 10 seconds for complete
        start = time.time()
        while time.time() - start < 10:
            state = await tab.evaluate("document.readyState")
            if state == "complete":
                break
            await asyncio.sleep(0.2)

    output({
        "ready": state == "complete",
        "state": state,
        "message": f"Document state: {state}"
    })


def main():
    parser = argparse.ArgumentParser(description="Wait for page")
    add_port_arg(parser)
    parser.add_argument("--idle", action="store_true", help="Wait for network idle")
    parser.add_argument("--sleep", type=float, help="Sleep for N seconds")
    parser.add_argument("--timeout", type=float, default=30, help="Timeout in seconds (default: 30)")
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
