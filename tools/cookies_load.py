#!/usr/bin/env python3
"""Load cookies from file into browser.

Usage:
    python tools/cookies_load.py [--port 9222] [--input ~/.nodriver-kit/cookies.dat]

Output:
    {"loaded": true, "message": "Cookies loaded"}
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools._common import output, error, add_port_arg, connect_browser, run_async

DEFAULT_COOKIES_FILE = Path("~/.nodriver-kit/cookies.dat").expanduser()


async def main_async(args):
    cookies_path = Path(args.input).expanduser()

    if not cookies_path.exists():
        error(f"Cookies file not found: {cookies_path}")

    browser = await connect_browser(args.port)

    try:
        await browser.cookies.load(str(cookies_path))
        output({
            "loaded": True,
            "path": str(cookies_path),
            "message": f"Cookies loaded from {cookies_path}"
        })
    except Exception as e:
        error(f"Failed to load cookies: {e}")


def main():
    parser = argparse.ArgumentParser(description="Load cookies")
    add_port_arg(parser)
    parser.add_argument("--input", "-i", default=str(DEFAULT_COOKIES_FILE), help="Input file path")
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
