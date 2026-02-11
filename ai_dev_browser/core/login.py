"""Interactive login - opens browser for manual login.

This is a human-in-the-loop tool: AI detects "not logged in" and calls this
to let the user log in manually. Cookies are saved automatically when the
user closes the browser.

Workflow:
    1. Start non-headless Chrome with a dedicated profile
    2. Load existing cookies, then navigate to the login URL
    3. Wait for user to log in and close the browser
    4. Chrome persists cookies to profile on exit (built-in)
    5. Start headless Chrome with same profile, export cookies to cookies.dat
"""

import asyncio
import sys

# Dedicated profile for interactive login sessions
_LOGIN_PROFILE = "login"


def login_interactive(url: str, cookies_path: str | None = None) -> dict:
    """Interactive login - opens browser for manual login.

    AI calls this when it detects the user is not logged in. A visible
    browser window opens for manual login; cookies are saved on close.

    Args:
        url: Login page URL
        cookies_path: Where to save cookies (default: ~/.ai-dev-browser/cookies.dat)

    Returns:
        Dict with success, cookies_saved, cookies_path keys.
    """
    return asyncio.run(_login_async(url, cookies_path))


async def _login_async(url: str, cookies_path: str | None) -> dict:
    from .browser import start_browser, stop_browser
    from .connection import connect_browser, get_active_tab
    from .cookies import load_cookies, save_cookies
    from .port import is_port_in_use

    # 1. Start non-headless Chrome with dedicated login profile
    result = start_browser(headless=False, profile=_LOGIN_PROFILE, reuse="none")
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
    print("  4. Cookies will be saved automatically", file=sys.stderr)
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

        # Wait for Chrome process to fully exit
        for _ in range(20):
            if not is_port_in_use(port=port):
                break
            await asyncio.sleep(0.3)

        print("Browser closed.", file=sys.stderr)

    except KeyboardInterrupt:
        return {"success": False, "error": "Interrupted by user"}
    except Exception as e:
        return {"success": False, "error": str(e)}

    # 4. Start headless Chrome with SAME profile to export cookies
    #    Chrome loads cookies from profile SQLite on startup — no race condition
    print("Saving cookies...", file=sys.stderr)
    try:
        result2 = start_browser(headless=True, profile=_LOGIN_PROFILE, reuse="none")
        if "error" in result2:
            return {"success": True, "cookies_saved": False, "error": result2["error"]}
        port2 = result2["port"]

        browser2 = await connect_browser(port=port2)
        tab2 = await get_active_tab(browser2)
        save_result = await save_cookies(tab2, path=cookies_path)

        # Clean up: stop the temporary headless Chrome
        stop_browser(port=port2)

        saved = save_result.get("saved", False)
        saved_path = save_result.get("path", "")
        if saved:
            print(f"Cookies saved to: {saved_path}", file=sys.stderr)
        else:
            print("Warning: save_cookies returned no result", file=sys.stderr)

        return {
            "success": True,
            "cookies_saved": saved,
            "cookies_path": saved_path,
        }

    except Exception as e:
        return {"success": True, "cookies_saved": False, "error": str(e)}
