#!/usr/bin/env python3
"""List running Chrome instances with debugging enabled.

Usage:
    python tools/browser_list.py

Output:
    {"browsers": [{"port": 9222, "pid": 1234, "in_use": false}, ...]}
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from nodriver_kit import find_temp_chromes, is_chrome_in_use, get_pid_on_port
from tools._common import output


def main():
    ports = find_temp_chromes()

    browsers = []
    for port in ports:
        pid = get_pid_on_port(port)
        browsers.append({"port": port, "pid": pid, "in_use": is_chrome_in_use(port)})

    output({"browsers": browsers, "count": len(browsers)})


if __name__ == "__main__":
    main()
