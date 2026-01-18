"""List running browser instances.

CLI:
    python -m nodriver_kit.tools.browser_list

Python:
    from nodriver_kit.tools import browser_list
    result = browser_list()
"""

import argparse
import json
from nodriver_kit.core import find_debug_chromes


def browser_list() -> dict:
    """List all running debug Chrome instances.

    Returns:
        {"browsers": [...], "count": ...}
    """
    try:
        browsers = find_debug_chromes()
        return {
            "browsers": browsers,
            "count": len(browsers),
        }
    except Exception as e:
        return {"error": f"List browsers failed: {e}"}


def cli_main():
    parser = argparse.ArgumentParser(description="List running browser instances")
    parser.parse_args()

    result = browser_list()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    cli_main()
