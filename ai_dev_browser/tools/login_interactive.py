"""Interactive login helper - opens browser for manual login.

CLI:
    python -m ai_dev_browser.tools.login_interactive --url "https://grok.com"
    python -m ai_dev_browser.tools.login_interactive --url "https://grok.com" --cookies-path ~/.ai-dev-browser/grok.dat

Python:
    from ai_dev_browser.tools import login_interactive
    result = login_interactive(url="https://grok.com")

Behavior:
    1. start_browser (non-headless, launch new Chrome)
    2. Navigate to the login URL
    3. Poll until user closes the browser - save cookies on each poll
    4. Return with last successful cookie save path
"""

import asyncio
import sys

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
    from ai_dev_browser.core.connection import connect_browser, get_active_tab
    from ai_dev_browser.core.cookies import load_cookies, save_cookies

    # 1. Start a new non-headless Chrome (reuse="none" to get a fresh one)
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
    print("  4. Cookies are saved automatically", file=sys.stderr)
    print(f"{'=' * 60}\n", file=sys.stderr)

    try:
        # 2. Connect, restore previous cookies, then navigate
        browser = await connect_browser(port=port)
        tab = await get_active_tab(browser)
        await load_cookies(
            tab, path=cookies_path
        )  # merge previous cookies (no-op if file missing)
        await tab.get(url)

        print("Waiting for you to log in and close the browser...", file=sys.stderr)

        # 3. Poll: save cookies periodically, stop when browser closes
        saved_path = ""
        while True:
            await asyncio.sleep(3)
            try:
                await tab.evaluate("1")  # heartbeat - throws if browser is gone
                # Browser still alive: save cookies (captures latest login state)
                try:
                    save_result = await save_cookies(tab, path=cookies_path)
                    if save_result.get("saved"):
                        saved_path = save_result.get("path", "")
                except Exception:
                    pass
            except Exception:
                # Browser closed
                break

        if saved_path:
            print(f"Cookies saved to: {saved_path}", file=sys.stderr)
        else:
            print("Warning: No cookies were saved", file=sys.stderr)

        return {
            "success": True,
            "cookies_saved": bool(saved_path),
            "cookies_path": saved_path,
        }

    except KeyboardInterrupt:
        return {"success": False, "error": "Interrupted by user"}
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    login_interactive.cli_main()
