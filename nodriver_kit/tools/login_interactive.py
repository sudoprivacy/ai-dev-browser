"""Interactive login helper - opens browser for manual login.

CLI:
    python -m nodriver_kit.tools.login_interactive --url "https://example.com/login"
    python -m nodriver_kit.tools.login_interactive --url "https://grok.com" --profile grok

Python:
    from nodriver_kit.tools import login_interactive
    result = login_interactive(url="https://example.com/login", profile="default")

Behavior:
    1. Opens browser with persistent profile
    2. Navigates to the login URL
    3. Waits for you to login and close the browser
    4. Session is automatically saved to profile
"""

import asyncio
import sys
from pathlib import Path
from ._cli import as_cli

DEFAULT_PROFILE_DIR = Path.home() / ".nodriver-kit" / "profiles"


@as_cli(requires_tab=False)
def login_interactive(url: str, profile: str = "default") -> dict:
    """Interactive login - opens browser for manual login.

    Args:
        url: Login page URL
        profile: Profile name for persistent storage

    Returns:
        {"success": True, "profile_dir": ...}
    """
    return asyncio.run(_login_async(url, profile))


async def _login_async(url: str, profile: str) -> dict:
    import nodriver

    profile_dir = DEFAULT_PROFILE_DIR / profile
    profile_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 60}", file=sys.stderr)
    print("MANUAL LOGIN REQUIRED", file=sys.stderr)
    print(f"{'=' * 60}", file=sys.stderr)
    print("", file=sys.stderr)
    print("This will:", file=sys.stderr)
    print("  1. Open browser with persistent profile", file=sys.stderr)
    print("  2. Navigate to the login URL", file=sys.stderr)
    print("  3. Wait for you to log in manually", file=sys.stderr)
    print("  4. Auto-save session when you CLOSE THE BROWSER", file=sys.stderr)
    print(f"{'=' * 60}\n", file=sys.stderr)

    browser = None
    try:
        print("Opening browser...", file=sys.stderr)
        browser = await nodriver.start(
            headless=False,
            user_data_dir=str(profile_dir),
        )

        tab = await browser.get(url)

        print(f"URL: {url}", file=sys.stderr)
        print(f"Profile: {profile_dir}", file=sys.stderr)
        print("", file=sys.stderr)
        print("Please log in, then CLOSE THE BROWSER when done.", file=sys.stderr)
        print(f"{'=' * 60}\n", file=sys.stderr)

        # Wait for browser to close
        while True:
            try:
                await asyncio.sleep(2)
                await tab.evaluate("1")
            except Exception:
                break

        print("Browser closed. Session saved.", file=sys.stderr)
        return {
            "success": True,
            "profile_dir": str(profile_dir),
        }

    except KeyboardInterrupt:
        return {"success": False, "error": "Interrupted by user"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        if browser:
            try:
                browser.stop()
            except Exception:
                pass


if __name__ == "__main__":
    login_interactive.cli_main()
