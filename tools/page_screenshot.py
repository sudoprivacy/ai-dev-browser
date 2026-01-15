#!/usr/bin/env python3
"""Take a screenshot of the current page.

Usage:
    python tools/page_screenshot.py [--port 9222] [--output /tmp/screenshot.png] [--full]

Output:
    {"path": "/tmp/screenshot.png", "message": "Screenshot saved"}

The AI can then use Read tool to view the screenshot.
"""

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools._common import output, error, add_port_arg, connect_browser, get_active_tab, run_async


async def main_async(args):
    browser = await connect_browser(args.port)
    tab = await get_active_tab(browser)

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = Path(tempfile.gettempdir()) / "nodriver_screenshot.png"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Take screenshot
    await tab.save_screenshot(str(output_path), full_page=args.full)

    output({
        "path": str(output_path),
        "full_page": args.full,
        "message": f"Screenshot saved to {output_path}"
    })


def main():
    parser = argparse.ArgumentParser(description="Take screenshot")
    add_port_arg(parser)
    parser.add_argument("--output", "-o", help="Output path (default: temp dir)")
    parser.add_argument("--full", "-f", action="store_true", help="Full page screenshot")
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
