"""Interactive login helper - opens browser for manual login.

CLI:
    python -m ai_dev_browser.tools.login_interactive --url "https://grok.com"
    python -m ai_dev_browser.tools.login_interactive --url "https://grok.com" --cookies-path ~/.ai-dev-browser/grok.dat

Python:
    from ai_dev_browser.tools import login_interactive
    result = login_interactive(url="https://grok.com")

Behavior:
    1. start_browser (non-headless, launch new Chrome)
    2. Load existing cookies, then navigate to the login URL
    3. Wait for user to log in and close the browser
    4. Save cookies on browser close, return
"""

import asyncio
import sys
from pathlib import Path

from .._cli import as_cli


@as_cli(requires_tab=False)
def login_interactive(url: str, cookies_path: str | None = None) -> dict:
    """Interactive login - opens browser for manual login.

    Args:
        url: Login page URL
        cookies_path: Where to save cookies (default: ~/.ai-dev-browser/cookies.dat)
    """
    return asyncio.run(_login_async(url, cookies_path))


async def _login_async(url: str, cookies_path: str | None) -> dict:
    from ai_dev_browser.core.browser import start_browser
    from ai_dev_browser.core.config import DEFAULT_COOKIES_FILE
    from ai_dev_browser.core.connection import connect_browser, get_active_tab
    from ai_dev_browser.core.cookies import load_cookies

    # 1. Start a new non-headless Chrome
    result = start_browser(headless=False, reuse="none")
    if "error" in result:
        return result
    port = result["port"]

    print(f"\n{'=' * 60}", file=sys.stderr)
    print("MANUAL LOGIN REQUIRED", file=sys.stderr)
    print(f"{'=' * 60}", file=sys.stderr)
    print(f"  URL:  {url}", file=sys.stderr)
    print(f"  Port: {port}", file=sys.stderr)
    print("", file=sys.stderr)
    print("  1. Browser will open and navigate to the URL", file=sys.stderr)
    print("  2. Please log in manually", file=sys.stderr)
    print("  3. Close the browser when done", file=sys.stderr)
    print("  4. Cookies will be saved on close", file=sys.stderr)
    print(f"{'=' * 60}\n", file=sys.stderr)

    try:
        # 2. Connect, restore previous cookies, then navigate
        browser = await connect_browser(port=port)
        tab = await get_active_tab(browser)
        await load_cookies(tab, path=cookies_path)  # no-op if file missing
        await tab.get(url)

        print("Waiting for you to log in and close the browser...", file=sys.stderr)

        # 3. Wait for browser to close (tab heartbeat)
        while True:
            await asyncio.sleep(0.5)
            try:
                await tab.evaluate("1")
            except Exception:
                break

        # 4. Save cookies — browser process lingers briefly after last tab closes
        save_path = Path(cookies_path or DEFAULT_COOKIES_FILE).expanduser()
        save_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            await browser.cookies.save(str(save_path))
            print(f"Cookies saved to: {save_path}", file=sys.stderr)
            return {
                "success": True,
                "cookies_saved": True,
                "cookies_path": str(save_path),
            }
        except Exception:
            print("Warning: Could not save cookies after close", file=sys.stderr)
            return {
                "success": True,
                "cookies_saved": False,
                "cookies_path": "",
            }

    except KeyboardInterrupt:
        return {"success": False, "error": "Interrupted by user"}
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    login_interactive.cli_main()
