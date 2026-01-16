#!/usr/bin/env python3
"""List running Chrome instances with debugging enabled.

Usage:
    python tools/browser_list.py

Output:
    {"browsers": [{"port": 9222, "pid": 1234, "in_use": false, "ours": true}, ...]}
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from nodriver_kit import find_debug_chromes, is_chrome_in_use, is_our_chrome_on_port, get_session_id
from tools._common import output


def main():
    chromes = find_debug_chromes()

    browsers = []
    for port, pid in chromes:
        is_ours, _ = is_our_chrome_on_port(port)
        browsers.append({
            "port": port,
            "pid": pid,
            "in_use": is_chrome_in_use(port),
            "ours": is_ours,
        })

    output({
        "session_id": get_session_id(),
        "browsers": browsers,
        "count": len(browsers),
    })


if __name__ == "__main__":
    main()
