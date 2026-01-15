#!/usr/bin/env python3
"""Interactive login helper - opens browser for manual login, saves cookies when done.

Usage:
    python tools/login_interactive.py --url "https://example.com/login" [--pattern "example"]

Behavior:
    1. Opens browser to the login URL
    2. Prints instructions - DOES NOT interact with the page
    3. Waits for you to login manually and close the browser
    4. Saves cookies automatically when browser closes

Output:
    {"success": true, "cookies_path": "~/.nodriver-kit/cookies.dat"}

For AI agents: when you detect no valid session, call this tool and wait.
The human will complete login and close the browser.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools._common import output, error

DEFAULT_COOKIES_FILE = Path("~/.nodriver-kit/cookies.dat").expanduser()


async def main_async(args):
    import nodriver

    cookies_path = Path(args.output).expanduser()
    cookies_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}", file=sys.stderr)
    print("MANUAL LOGIN REQUIRED", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"", file=sys.stderr)
    print("This script will:", file=sys.stderr)
    print("  1. Open a browser window", file=sys.stderr)
    print("  2. Navigate to the login URL", file=sys.stderr)
    print("  3. Wait for you to log in manually", file=sys.stderr)
    print("  4. Save cookies when you CLOSE THE BROWSER", file=sys.stderr)
    print(f"", file=sys.stderr)
    print("The script will NOT interact with the page.", file=sys.stderr)
    print("Take your time to log in.", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)

    browser = None
    try:
        # Start browser (headful)
        print("Opening browser...", file=sys.stderr)
        browser = await nodriver.start(headless=False)

        # Navigate to login page
        tab = await browser.get(args.url)

        print(f"", file=sys.stderr)
        print(f"URL: {args.url}", file=sys.stderr)
        print(f"Cookies will be saved to: {cookies_path}", file=sys.stderr)
        print(f"", file=sys.stderr)
        print("Please log in, then CLOSE THE BROWSER when done.", file=sys.stderr)
        print(f"{'='*60}\n", file=sys.stderr)

        # Wait for browser to close
        # Poll until no more targets (browser closed)
        while True:
            try:
                targets = await browser.targets
                if not targets:
                    break
                await asyncio.sleep(1)
            except Exception:
                # Connection lost = browser closed
                break

        # Save cookies
        print("Browser closed. Saving cookies...", file=sys.stderr)
        try:
            if args.pattern:
                await browser.cookies.save(str(cookies_path), pattern=args.pattern)
            else:
                await browser.cookies.save(str(cookies_path))

            output({
                "success": True,
                "cookies_path": str(cookies_path),
                "message": "Login complete, cookies saved"
            })
        except Exception as e:
            # Browser already closed, cookies might not be saveable
            output({
                "success": True,
                "cookies_path": str(cookies_path),
                "message": "Browser closed (cookies may have been saved by browser)"
            })

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
    parser.add_argument("--output", "-o", default=str(DEFAULT_COOKIES_FILE), help="Cookies output path")
    parser.add_argument("--pattern", "-p", help="Cookie domain pattern to save (e.g., 'grok')")
    args = parser.parse_args()

    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
