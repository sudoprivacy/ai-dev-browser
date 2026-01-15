#!/usr/bin/env python3
"""Execute JavaScript in the page context.

Usage:
    python tools/js_execute.py --code "document.title" [--port 9222]
    python tools/js_execute.py --code "document.querySelectorAll('a').length" [--port 9222]

Output:
    {"result": "Example Domain"}
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools._common import output, error, add_port_arg, connect_browser, get_active_tab, run_async


async def main_async(args):
    browser = await connect_browser(args.port)
    tab = await get_active_tab(browser)

    try:
        result = await tab.evaluate(args.code)
        output({
            "result": result,
            "type": type(result).__name__
        })
    except Exception as e:
        error(f"JS execution failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Execute JavaScript")
    add_port_arg(parser)
    parser.add_argument("--code", "-c", required=True, help="JavaScript code to execute")
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
