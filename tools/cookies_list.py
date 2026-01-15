#!/usr/bin/env python3
"""List current browser cookies.

Usage:
    python tools/cookies_list.py [--port 9222]
    python tools/cookies_list.py --domain "example.com"

Output:
    {"cookies": [{"name": "session", "domain": ".example.com", "value": "..."}], "count": 5}
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools._common import output, error, add_port_arg, connect_browser, run_async


async def main_async(args):
    browser = await connect_browser(args.port)

    try:
        cookies = await browser.cookies.get_all()

        # Filter by domain if specified
        if args.domain:
            cookies = [c for c in cookies if args.domain in (c.get("domain", "") or "")]

        # Simplify output
        simple_cookies = []
        for c in cookies:
            simple_cookies.append({
                "name": c.get("name"),
                "domain": c.get("domain"),
                "path": c.get("path", "/"),
                "secure": c.get("secure", False),
                "httpOnly": c.get("httpOnly", False),
                "value": c.get("value", "")[:50] + "..." if len(c.get("value", "")) > 50 else c.get("value", "")
            })

        output({
            "cookies": simple_cookies,
            "count": len(simple_cookies)
        })

    except Exception as e:
        error(f"Failed to get cookies: {e}")


def main():
    parser = argparse.ArgumentParser(description="List cookies")
    add_port_arg(parser)
    parser.add_argument("--domain", "-d", help="Filter by domain")
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
