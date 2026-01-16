#!/usr/bin/env python3
"""Save browser cookies to file.

Usage:
    python tools/cookies_save.py [--port 9222] [--output ~/.nodriver-kit/cookies.dat] [--pattern ""]

Output:
    {"path": "~/.nodriver-kit/cookies.dat", "message": "Cookies saved"}
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from nodriver_kit import DEFAULT_COOKIES_FILE
from tools._common import output, error, add_port_arg, connect_browser, run_async


async def main_async(args):
    browser = await connect_browser(args.port)

    cookies_path = Path(args.output).expanduser()
    cookies_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if args.pattern:
            await browser.cookies.save(str(cookies_path), pattern=args.pattern)
        else:
            await browser.cookies.save(str(cookies_path))

        output({
            "path": str(cookies_path),
            "pattern": args.pattern or "all",
            "message": f"Cookies saved to {cookies_path}"
        })
    except Exception as e:
        error(f"Failed to save cookies: {e}")


def main():
    parser = argparse.ArgumentParser(description="Save cookies")
    add_port_arg(parser)
    parser.add_argument("--output", "-o", default=str(DEFAULT_COOKIES_FILE), help="Output file path")
    parser.add_argument("--pattern", help="Only save cookies matching pattern (e.g., 'grok')")
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
