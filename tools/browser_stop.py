#!/usr/bin/env python3
"""Stop a running Chrome browser.

Usage:
    python tools/browser_stop.py --port 9222    # Stop specific port
    python tools/browser_stop.py --all          # Stop all debug Chromes (9222-9300)

Output:
    {"stopped": true, "port": 9222, "pid": 12345}
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from nodriver_kit import (
    kill_process_tree,
    get_pid_on_port,
    find_debug_chromes,
    cleanup_temp_profile,
)
from tools._common import output, error


def main():
    parser = argparse.ArgumentParser(description="Stop Chrome browser")
    parser.add_argument(
        "--port", "-p", type=int, help="Stop browser on specific port (required)"
    )
    parser.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="Stop all Chrome instances on debug ports (9222-9300)",
    )
    args = parser.parse_args()

    if args.all:
        # Find and stop all debug Chromes
        chromes = find_debug_chromes()
        if not chromes:
            output(
                {
                    "stopped": False,
                    "message": "No Chrome instances found on debug ports",
                }
            )
            return

        stopped = []
        cleaned = 0
        for port, pid in chromes:
            try:
                kill_process_tree(pid)
                stopped.append({"port": port, "pid": pid})
                # Clean up temp profile if exists
                if cleanup_temp_profile(port):
                    cleaned += 1
            except Exception:
                pass
        result = {"stopped": True, "count": len(stopped), "browsers": stopped}
        if cleaned > 0:
            result["temp_profiles_cleaned"] = cleaned
        output(result)

    elif args.port:
        # Stop specific port directly (works for both temp and persistent profiles)
        pid = get_pid_on_port(args.port)
        if pid:
            try:
                kill_process_tree(pid)
                # Clean up temp profile if exists
                cleaned = cleanup_temp_profile(args.port)
                result = {"stopped": True, "port": args.port, "pid": pid}
                if cleaned:
                    result["temp_profile_cleaned"] = True
                output(result)
            except Exception as e:
                error(f"Failed to stop browser on port {args.port}: {e}")
        else:
            error(f"No browser found on port {args.port}")

    else:
        error("Please specify --port or --all")


if __name__ == "__main__":
    main()
