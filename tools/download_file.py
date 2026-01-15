#!/usr/bin/env python3
"""Download a file from URL.

Usage:
    python tools/download_file.py --url "https://example.com/file.pdf"
    python tools/download_file.py --url "https://example.com/file.pdf" --output "/tmp/myfile.pdf"

Output:
    {"url": "...", "path": "/tmp/file.pdf", "message": "Downloaded file"}
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

    output_path = args.output
    if output_path:
        output_path = Path(output_path).expanduser().resolve()

    try:
        result_path = await tab.download_file(args.url, output_path)

        output(
            {
                "url": args.url,
                "path": str(result_path) if result_path else None,
                "message": "Downloaded file",
            }
        )

    except Exception as e:
        error(f"Download failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Download file")
    add_port_arg(parser)
    parser.add_argument("--url", "-u", required=True, help="URL to download")
    parser.add_argument("--output", "-o", help="Output file path (default: auto)")
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
