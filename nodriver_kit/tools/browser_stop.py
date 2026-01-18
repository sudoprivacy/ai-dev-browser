"""Stop browser instance(s).

CLI:
    python -m nodriver_kit.tools.browser_stop --port 9222
    python -m nodriver_kit.tools.browser_stop --all

Python:
    from nodriver_kit.tools import browser_stop
    result = await browser_stop(port=9222)
"""

import argparse
import asyncio
import json
from nodriver_kit.core import (
    find_our_chromes,
    kill_process_tree,
    cleanup_temp_profile,
    get_pid_on_port,
)


async def browser_stop(port: int = None, all: bool = False) -> dict:
    """Stop browser instance(s).

    Args:
        port: Port of browser to stop
        all: Stop all our browser instances

    Returns:
        {"stopped": True, "count": ...}
    """
    try:
        if not port and not all:
            return {"error": "Please specify --port or --all"}

        stopped = []

        if all:
            browsers = find_our_chromes()
            for browser in browsers:
                try:
                    kill_process_tree(browser["pid"])
                    if browser.get("profile_dir"):
                        cleanup_temp_profile(browser["profile_dir"])
                    stopped.append({"port": browser["port"], "pid": browser["pid"]})
                except Exception:
                    pass
        else:
            pid = get_pid_on_port(port)
            if pid:
                kill_process_tree(pid)
                stopped.append({"port": port, "pid": pid})

        return {
            "stopped": True,
            "count": len(stopped),
            "browsers": stopped,
        }
    except Exception as e:
        return {"error": f"Stop browser failed: {e}"}


def cli_main():
    parser = argparse.ArgumentParser(description="Stop browser instance(s)")
    parser.add_argument("--port", "-p", type=int, help="Port to stop")
    parser.add_argument("--all", "-a", action="store_true", help="Stop all")
    args = parser.parse_args()

    result = asyncio.run(browser_stop(port=args.port, all=args.all))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    cli_main()
