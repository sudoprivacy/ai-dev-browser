#!/usr/bin/env python3
"""Interactive login helper - opens browser for manual login, saves session when done.

Usage:
    python tools/login_interactive.py --url "https://example.com/login"
    python tools/login_interactive.py --url "https://gemini.google.com" --profile gemini

Behavior:
    1. Opens browser with persistent profile (cookies auto-saved)
    2. Navigates to the login URL
    3. Waits for you to login manually and close the browser
    4. Session is automatically persisted to profile directory

Output:
    {"success": true, "profile_dir": "~/.nodriver-kit/profiles/default"}

For AI agents: when you detect no valid session, call this tool and wait.
The human will complete login and close the browser.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from nodriver_kit import DEFAULT_PROFILE_DIR
from tools._common import output, error


async def main_async(args):
    import nodriver

    # Use persistent profile directory (like Playwright's launch_persistent_context)
    profile_dir = DEFAULT_PROFILE_DIR / args.profile
    profile_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 60}", file=sys.stderr)
    print("MANUAL LOGIN REQUIRED", file=sys.stderr)
    print(f"{'=' * 60}", file=sys.stderr)
    print("", file=sys.stderr)
    print("This script will:", file=sys.stderr)
    print("  1. Open a browser window with persistent profile", file=sys.stderr)
    print("  2. Navigate to the login URL", file=sys.stderr)
    print("  3. Wait for you to log in manually", file=sys.stderr)
    print("  4. Auto-save session when you CLOSE THE BROWSER", file=sys.stderr)
    print("", file=sys.stderr)
    print("The script will NOT interact with the page.", file=sys.stderr)
    print("Take your time to log in.", file=sys.stderr)
    print(f"{'=' * 60}\n", file=sys.stderr)

    browser = None
    try:
        # Start browser with persistent profile (cookies auto-saved to disk)
        print("Opening browser...", file=sys.stderr)
        browser = await nodriver.start(
            headless=False,
            user_data_dir=str(profile_dir),
        )

        # Navigate to login page
        tab = await browser.get(args.url)

        print("", file=sys.stderr)
        print(f"URL: {args.url}", file=sys.stderr)
        print(f"Profile: {profile_dir}", file=sys.stderr)
        print("", file=sys.stderr)
        print("Please log in, then CLOSE THE BROWSER when done.", file=sys.stderr)
        print("(Session will be auto-saved to profile)", file=sys.stderr)
        print(f"{'=' * 60}\n", file=sys.stderr)

        # Wait for browser to close by polling tab connection
        while True:
            try:
                await asyncio.sleep(2)
                # This will fail when browser is closed
                _ = await tab.evaluate("1")
            except Exception:
                break

        print("Browser closed. Session saved to profile.", file=sys.stderr)
        output(
            {
                "success": True,
                "profile_dir": str(profile_dir),
                "message": f"Login complete, session saved to {profile_dir}",
            }
        )

    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        error("Interrupted by user")
    except Exception as e:
        error(f"Error: {e}")
    finally:
        if browser:
            try:
                await browser.stop()
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="Interactive login helper")
    parser.add_argument("--url", "-u", required=True, help="Login page URL")
    parser.add_argument(
        "--profile",
        "-p",
        default="default",
        help="Profile name (stored in ~/.nodriver-kit/profiles/)",
    )
    args = parser.parse_args()

    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
