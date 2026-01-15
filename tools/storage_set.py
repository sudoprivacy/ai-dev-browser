#!/usr/bin/env python3
"""Set localStorage data.

Usage:
    python tools/storage_set.py --key "theme" --value "dark"
    python tools/storage_set.py --json '{"theme": "dark", "lang": "en"}'

Output:
    {"set": {"theme": "dark"}, "message": "Set 1 item(s)"}
"""

import argparse
import json
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
        if args.json:
            items = json.loads(args.json)
        else:
            items = {args.key: args.value}

        await tab.set_local_storage(items)

        output({"set": items, "message": f"Set {len(items)} item(s)"})

    except json.JSONDecodeError as e:
        error(f"Invalid JSON: {e}")
    except Exception as e:
        error(f"Failed to set localStorage: {e}")


def main():
    parser = argparse.ArgumentParser(description="Set localStorage")
    add_port_arg(parser)
    parser.add_argument("--key", "-k", help="Key to set")
    parser.add_argument("--value", "-v", help="Value to set")
    parser.add_argument(
        "--json", "-j", help="JSON object with multiple key-value pairs"
    )
    args = parser.parse_args()

    if not args.json and (not args.key or args.value is None):
        error("Must specify --key and --value, or --json")

    run_async(main_async(args))


if __name__ == "__main__":
    main()
