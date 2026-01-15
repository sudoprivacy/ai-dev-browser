#!/usr/bin/env python3
"""Get localStorage data.

Usage:
    python tools/storage_get.py [--port 9222]
    python tools/storage_get.py --key "user_settings"

Output:
    {"storage": {"key1": "value1", ...}, "count": 5}
    or for specific key:
    {"key": "user_settings", "value": "...", "found": true}
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
        storage = await tab.get_local_storage()

        if args.key:
            value = storage.get(args.key)
            output({"key": args.key, "value": value, "found": value is not None})
        else:
            output({"storage": storage, "count": len(storage)})

    except Exception as e:
        error(f"Failed to get localStorage: {e}")


def main():
    parser = argparse.ArgumentParser(description="Get localStorage")
    add_port_arg(parser)
    parser.add_argument("--key", "-k", help="Specific key to get (default: all)")
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
