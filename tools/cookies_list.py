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
            cookies = [
                c for c in cookies if args.domain in (getattr(c, "domain", "") or "")
            ]

        # Simplify output - cookies are Cookie objects, not dicts
        simple_cookies = []
        for c in cookies:
            value = getattr(c, "value", "") or ""
            simple_cookies.append(
                {
                    "name": getattr(c, "name", ""),
                    "domain": getattr(c, "domain", ""),
                    "path": getattr(c, "path", "/"),
                    "secure": getattr(c, "secure", False),
                    "httpOnly": getattr(c, "http_only", False),
                    "value": value[:50] + "..." if len(value) > 50 else value,
                }
            )

        output({"cookies": simple_cookies, "count": len(simple_cookies)})

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
