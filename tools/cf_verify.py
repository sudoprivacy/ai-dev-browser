#!/usr/bin/env python3
"""Verify and bypass Cloudflare challenge.

Requires: pip install opencv-python

Usage:
    python tools/cf_verify.py [--port 9222]
    python tools/cf_verify.py --retries 10

Output:
    {"verified": true, "message": "Cloudflare challenge passed"}
    or
    {"verified": false, "message": "No challenge detected"}
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

    try:
        # Use nodriver's native verify_cf
        await tab.verify_cf()
        output({"verified": True, "message": "Cloudflare challenge passed"})
    except Exception as e:
        error_msg = str(e).lower()
        if "no cf" in error_msg or "not found" in error_msg:
            output(
                {
                    "verified": True,
                    "challenge_present": False,
                    "message": "No Cloudflare challenge detected",
                }
            )
        elif "opencv" in error_msg or "cv2" in error_msg:
            error("opencv-python not installed. Run: pip install opencv-python")
        else:
            output(
                {"verified": False, "message": f"Cloudflare verification failed: {e}"}
            )


def main():
    parser = argparse.ArgumentParser(description="Verify Cloudflare")
    add_port_arg(parser)
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
