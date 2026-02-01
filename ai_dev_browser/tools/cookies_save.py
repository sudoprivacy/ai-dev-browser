"""Save browser cookies to file."""

from pathlib import Path

from ai_dev_browser import DEFAULT_COOKIES_FILE

from .._cli import as_cli


@as_cli()
async def cookies_save(tab, output: str = None, pattern: str = None) -> dict:
    """Save browser cookies to file.

    Args:
        tab: Browser tab
        output: Output file path (default: ~/.ai-dev-browser/cookies.dat)
        pattern: Only save cookies matching pattern
    """
    try:
        cookies_path = Path(output or DEFAULT_COOKIES_FILE).expanduser()
        cookies_path.parent.mkdir(parents=True, exist_ok=True)

        browser = tab.browser
        if pattern:
            await browser.cookies.save(str(cookies_path), pattern=pattern)
        else:
            await browser.cookies.save(str(cookies_path))

        return {
            "path": str(cookies_path),
            "pattern": pattern or "all",
            "saved": True,
        }
    except Exception as e:
        return {"error": f"Save cookies failed: {e}"}


if __name__ == "__main__":
    cookies_save.cli_main()
