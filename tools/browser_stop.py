#!/usr/bin/env python3
"""Stop a running Chrome browser.

Usage:
    python tools/browser_stop.py [--port 9222]
    python tools/browser_stop.py --all

Output:
    {"stopped": true, "port": 9222}
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from nodriver_kit import find_temp_chromes, kill_process_tree
from tools._common import output, error


def main():
    parser = argparse.ArgumentParser(description="Stop Chrome browser")
    parser.add_argument("--port", "-p", type=int, help="Stop browser on specific port")
    parser.add_argument("--all", "-a", action="store_true", help="Stop all nodriver Chrome instances")
    args = parser.parse_args()

    chromes = find_temp_chromes()

    if not chromes:
        output({"stopped": False, "message": "No nodriver Chrome instances found"})
        return

    stopped = []

    if args.all:
        for port, pid in chromes:
            try:
                kill_process_tree(pid)
                stopped.append({"port": port, "pid": pid})
            except Exception as e:
                pass
        output({"stopped": True, "count": len(stopped), "browsers": stopped})

    elif args.port:
        for port, pid in chromes:
            if port == args.port:
                try:
                    kill_process_tree(pid)
                    output({"stopped": True, "port": port, "pid": pid})
                    return
                except Exception as e:
                    error(f"Failed to stop browser on port {port}: {e}")
        error(f"No browser found on port {args.port}")

    else:
        # Stop first one
        port, pid = chromes[0]
        try:
            kill_process_tree(pid)
            output({"stopped": True, "port": port, "pid": pid})
        except Exception as e:
            error(f"Failed to stop browser: {e}")


if __name__ == "__main__":
    main()
