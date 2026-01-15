#!/usr/bin/env python3
"""Start a Chrome browser with remote debugging.

Usage:
    python tools/browser_start.py [--port 9222] [--headless]

Output:
    {"port": 9222, "message": "Browser started"}
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from nodriver_kit import launch_chrome, get_available_port, is_port_in_use
from tools._common import output, error


def main():
    parser = argparse.ArgumentParser(description="Start Chrome browser")
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=9222,
        help="Debugging port (default: 9222, auto-finds if busy)"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in headless mode (default: show browser)"
    )
    args = parser.parse_args()

    # Find available port
    port = args.port
    if is_port_in_use("127.0.0.1", port):
        port = get_available_port(start=port + 1)

    try:
        process = launch_chrome(port=port, headless=args.headless)
        output({
            "port": port,
            "pid": process.pid,
            "headless": args.headless,
            "message": f"Browser started on port {port}"
        })
    except FileNotFoundError as e:
        error(f"Chrome not found: {e}")
    except Exception as e:
        error(f"Failed to start browser: {e}")


if __name__ == "__main__":
    main()
