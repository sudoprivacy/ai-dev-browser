"""Cookie management operations."""

from pathlib import Path

from ._tab import Tab

from . import DEFAULT_COOKIES_FILE


async def cookies_load(
    tab: Tab,
    path: str | None = None,
) -> dict:
    """Load cookies from file into browser.

    Args:
        tab: Tab instance
        path: Path to cookies file (default: ~/.ai-dev-browser/cookies.dat)

    Returns:
        dict with path, loaded status
    """
    cookies_path = Path(path or DEFAULT_COOKIES_FILE).expanduser()

    if not cookies_path.exists():
        return {"error": f"Cookies file not found: {cookies_path}"}

    browser = tab.browser
    await browser.cookies.load(str(cookies_path))

    return {
        "path": str(cookies_path),
        "loaded": True,
    }


async def cookies_save(
    tab: Tab,
    path: str | None = None,
    pattern: str | None = None,
) -> dict:
    """Save browser cookies to file.

    Args:
        tab: Tab instance
        path: Path to save cookies (default: ~/.ai-dev-browser/cookies.dat)
        pattern: Only save cookies matching pattern

    Returns:
        dict with path, pattern, saved status
    """
    cookies_path = Path(path or DEFAULT_COOKIES_FILE).expanduser()
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


async def cookies_list(
    tab: Tab,
    domain: str | None = None,
) -> dict:
    """List browser cookies.

    Args:
        tab: Tab instance
        domain: Filter by domain (optional)

    Returns:
        dict with cookies list and count
    """
    browser = tab.browser
    cookies = await browser.cookies.get_all()

    # Filter by domain if specified
    if domain:
        cookies = [c for c in cookies if domain in (getattr(c, "domain", "") or "")]

    # Simplify output
    simple_cookies = []
    for c in cookies:
        value = getattr(c, "value", "") or ""
        simple_cookies.append(
            {
                "name": getattr(c, "name", ""),
                "domain": getattr(c, "domain", ""),
                "path": getattr(c, "path", "/"),
                "secure": getattr(c, "secure", False),
                "httpOnly": getattr(c, "http_only", False),
                "value": value[:50] + "..." if len(value) > 50 else value,
            }
        )

    return {"cookies": simple_cookies, "count": len(simple_cookies)}
