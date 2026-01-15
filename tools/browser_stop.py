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

from nodriver_kit import kill_process_tree, get_pid_on_port, is_port_in_use
from tools._common import output, error


def find_debug_chromes(port_range: tuple = (9222, 9300)) -> list:
    """Find all Chrome instances listening on debug ports."""
    ports = []
    for port in range(port_range[0], port_range[1]):
        if is_port_in_use("127.0.0.1", port):
            pid = get_pid_on_port(port)
            if pid:
                ports.append((port, pid))
    return ports


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
        for port, pid in chromes:
            try:
                kill_process_tree(pid)
                stopped.append({"port": port, "pid": pid})
            except Exception:
                pass
        output({"stopped": True, "count": len(stopped), "browsers": stopped})

    elif args.port:
        # Stop specific port directly (works for both temp and persistent profiles)
        pid = get_pid_on_port(args.port)
        if pid:
            try:
                kill_process_tree(pid)
                output({"stopped": True, "port": args.port, "pid": pid})
            except Exception as e:
                error(f"Failed to stop browser on port {args.port}: {e}")
        else:
            error(f"No browser found on port {args.port}")

    else:
        error("Please specify --port or --all")


if __name__ == "__main__":
    main()
