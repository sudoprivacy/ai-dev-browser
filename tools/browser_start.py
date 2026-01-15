#!/usr/bin/env python3
"""Start a Chrome browser with remote debugging.

Usage:
    python tools/browser_start.py                    # Default: persistent profile
    python tools/browser_start.py --profile gemini   # Named persistent profile
    python tools/browser_start.py --temp             # Temp profile (deleted on close)

Profile modes:
    - Default: Persistent profile (~/.nodriver-kit/profiles/default/)
      Better for anti-detection (looks like returning user with history)
    - --profile <name>: Named persistent profile
    - --temp: Temp profile, deleted on close (for testing/scraping)

Output:
    {"port": 9222, "profile": "default", "message": "Browser started"}
"""

import argparse
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from nodriver_kit import launch_chrome, get_available_port, is_port_in_use
from tools._common import output, error

DEFAULT_PROFILE_DIR = Path("~/.nodriver-kit/profiles").expanduser()


def main():
    parser = argparse.ArgumentParser(description="Start Chrome browser")
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=9222,
        help="Debugging port (default: 9222, auto-finds if busy)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in headless mode (default: visible)",
    )
    parser.add_argument(
        "--profile",
        default="default",
        help="Persistent profile name (default: 'default'). "
        "Stored in ~/.nodriver-kit/profiles/<name>/",
    )
    parser.add_argument(
        "--temp",
        action="store_true",
        help="Use temp profile instead (deleted on close). "
        "Use for testing or when you need fresh browser.",
    )
    args = parser.parse_args()

    # Find available port
    port = args.port
    if is_port_in_use("127.0.0.1", port):
        port = get_available_port(start=port + 1)

    # Determine profile directory
    if args.temp:
        user_data_dir = None
        profile_name = "temp"
    else:
        profile_dir = DEFAULT_PROFILE_DIR / args.profile
        profile_dir.mkdir(parents=True, exist_ok=True)
        user_data_dir = str(profile_dir)
        profile_name = args.profile

    try:
        process = launch_chrome(
            port=port, headless=args.headless, user_data_dir=user_data_dir
        )
        result = {
            "port": port,
            "pid": process.pid,
            "headless": args.headless,
            "profile": profile_name,
            "message": f"Browser started on port {port}",
        }
        if not args.temp:
            result["profile_dir"] = user_data_dir
        output(result)
    except FileNotFoundError as e:
        error(f"Chrome not found: {e}")
    except Exception as e:
        error(f"Failed to start browser: {e}")


if __name__ == "__main__":
    main()
