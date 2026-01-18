"""Load cookies from file into browser.

CLI:
    python -m nodriver_kit.tools.cookies_load --input "cookies.dat"

Python:
    from nodriver_kit.tools import cookies_load
    result = await cookies_load(tab, input="cookies.dat")
"""

from pathlib import Path
from nodriver_kit import DEFAULT_COOKIES_FILE
from ._cli import as_cli


@as_cli
async def cookies_load(tab, input: str = None) -> dict:
    """Load cookies from file into browser.

    Args:
        tab: Browser tab
        input: Input file path (default: ~/.nodriver-kit/cookies.dat)

    Returns:
        {"path": ..., "loaded": True}
    """
    try:
        cookies_path = Path(input or DEFAULT_COOKIES_FILE).expanduser()

        if not cookies_path.exists():
            return {"error": f"Cookies file not found: {cookies_path}"}

        browser = tab.browser
        await browser.cookies.load(str(cookies_path))

        return {
            "path": str(cookies_path),
            "loaded": True,
        }
    except Exception as e:
        return {"error": f"Load cookies failed: {e}"}


if __name__ == "__main__":
    cookies_load.cli_main()
