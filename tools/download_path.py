#!/usr/bin/env python3
"""Set download directory for the browser.

Usage:
    python tools/download_path.py --path "/tmp/downloads"
    python tools/download_path.py --path "C:\\Users\\me\\Downloads"

Output:
    {"path": "/tmp/downloads", "message": "Download path set"}
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

    path = Path(args.path).expanduser().resolve()

    # Create directory if it doesn't exist
    path.mkdir(parents=True, exist_ok=True)

    try:
        await tab.set_download_path(str(path))

        output({"path": str(path), "message": "Download path set"})

    except Exception as e:
        error(f"Failed to set download path: {e}")


def main():
    parser = argparse.ArgumentParser(description="Set download path")
    add_port_arg(parser)
    parser.add_argument("--path", "-d", required=True, help="Download directory path")
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
