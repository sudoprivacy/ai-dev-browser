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


async def cookies_extract_live(
    tab: Tab,
    domain: str,
) -> list[dict]:
    """Use when: you need a domain's cookies from a **running** browser —
    the live, already-decrypted store — including in-memory session
    cookies and Chrome 127+ App-Bound (v20) cookies that the on-disk path
    (`cookies_extract_offline`) cannot read. Returns full cookie dicts
    (identical shape to `cookies_extract_offline`), so the two are
    interchangeable once `--port` points at the right browser.

    Reads over CDP (`Storage.getCookies`) from whatever Chrome `--port` is
    attached to — the automation instance, or a user Chrome launched with
    `--remote-debugging-port`. Because the browser already holds every
    cookie decrypted in memory, this side-steps both disk failure modes at
    once: no SQLite, no DPAPI/Keychain, no App-Bound key, and session
    cookies that were never written to disk are visible too. Unlike
    `document.cookie` via `js_evaluate`, httpOnly cookies — the
    auth/session ones you actually want — are included.

    To copy a login *out of* the user's browser *into* a separate
    automation session, run `cookies_save` on the source `--port` then
    `cookies_load` on the destination `--port`; this tool is for reading
    the values back (a one-time code, a token) or confirming what is set.

    Args:
        tab: Tab instance. Selects which browser to read from; the read is
            browser-wide, not scoped to this tab.
        domain: Substring matched against each cookie's domain, e.g.
            "google.com" or ".proton.me". "" returns every cookie — same
            semantics as `cookies_extract_offline`.

    Returns:
        List of cookie dicts with keys: name, value, domain, path, secure,
        httpOnly, expires (Unix seconds, or None for a session cookie).

    Failure:
        Empty result means the attached browser has no cookie whose domain
        contains that substring — you may be on the wrong Chrome (set
        `--port`/`--tab-url` to the browser that is logged in) or the
        session is not established yet (log in first). To read a user's
        already-open login they must have started Chrome with
        `--remote-debugging-port` so you can attach to it.
    """
    browser = tab.browser
    cookies = await browser.cookies.get_all()

    result = []
    for c in cookies:
        cookie_domain = getattr(c, "domain", "") or ""
        if domain and domain not in cookie_domain:
            continue

        # Session cookies (and any with no future expiry) report as None —
        # mirrors the on-disk path so both extractors return one shape.
        session = getattr(c, "session", False)
        expires = getattr(c, "expires", None)
        expires_out = None if session or not expires or expires < 0 else expires

        result.append(
            {
                "name": getattr(c, "name", ""),
                "value": getattr(c, "value", "") or "",
                "domain": cookie_domain,
                "path": getattr(c, "path", "/"),
                "secure": bool(getattr(c, "secure", False)),
                "httpOnly": bool(getattr(c, "http_only", False)),
                "expires": expires_out,
            }
        )

    return result
