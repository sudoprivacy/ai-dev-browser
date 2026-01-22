"""List browser cookies.

CLI:
    python -m nodriver_kit.tools.cookies_list
    python -m nodriver_kit.tools.cookies_list --domain "example.com"

Python:
    from nodriver_kit.tools import cookies_list
    result = await cookies_list(tab, domain="example.com")
"""

from ._cli import as_cli


@as_cli()
async def cookies_list(tab, domain: str = None) -> dict:
    """List browser cookies.

    Args:
        tab: Browser tab
        domain: Filter by domain (optional)

    Returns:
        {"cookies": [...], "count": ...}
    """
    try:
        browser = tab.browser
        cookies = await browser.cookies.get_all()

        # Filter by domain if specified
        if domain:
            cookies = [c for c in cookies if domain in (getattr(c, "domain", "") or "")]

        # Simplify output
        simple_cookies = []
        for c in cookies:
            value = getattr(c, "value", "") or ""
            simple_cookies.append({
                "name": getattr(c, "name", ""),
                "domain": getattr(c, "domain", ""),
                "path": getattr(c, "path", "/"),
                "secure": getattr(c, "secure", False),
                "httpOnly": getattr(c, "http_only", False),
                "value": value[:50] + "..." if len(value) > 50 else value,
            })

        return {"cookies": simple_cookies, "count": len(simple_cookies)}
    except Exception as e:
        return {"error": f"List cookies failed: {e}"}


if __name__ == "__main__":
    cookies_list.cli_main()
