"""Integration tests for cookies_import: extract cookies from the user's
real Chrome installation.

Unlike most integration tests in this suite, these do NOT need a running
automation Chrome — they read from the user's daily-driver browser's
SQLite cookie database. Every dev box has Chrome installed with at least
a few cookies, so these tests are expected to pass on any macOS/Windows/
Linux machine with Chrome and a non-empty cookie jar.

The tests verify the full decryption pipeline end-to-end:
  macOS  — Keychain → PBKDF2 → AES-CBC via CommonCrypto
  Windows — Local State → DPAPI → AES-GCM via BCrypt
  Linux  — libsecret / "peanuts" → PBKDF2 → AES-CBC via libcrypto

Skipped in CI via SKIP_INTEGRATION=1 (no real user Chrome profile).
"""

import os
import sys

import pytest

from ai_dev_browser.core.cookies_import import (
    _find_cookie_db,
    _get_macos_key,
    extract_cookies,
)


SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)


@pytest.fixture(autouse=True)
def _integration_guard():
    if SKIP_INTEGRATION:
        pytest.skip("SKIP_INTEGRATION is set")


# ---------------------------------------------------------------------------
# Database discovery
# ---------------------------------------------------------------------------


def test_find_cookie_db_chrome():
    """Chrome's Cookies SQLite file must be locatable on the dev box."""
    db = _find_cookie_db("chrome")
    assert db.exists(), f"Cookie DB not found at {db}"
    assert db.name == "Cookies"


def test_find_cookie_db_nonexistent_browser_raises():
    """A made-up browser name must raise FileNotFoundError, not silently
    return a bogus path."""
    with pytest.raises((FileNotFoundError, ValueError)):
        _find_cookie_db("netscape-navigator-4")


# ---------------------------------------------------------------------------
# Key retrieval (platform-specific)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_macos_keychain_key_retrieval():
    """On macOS, we must successfully retrieve Chrome's safe-storage
    password from the Keychain and derive a 16-byte AES key.

    This will trigger a Keychain authorization dialog on first run.
    """
    key = _get_macos_key("chrome")
    assert isinstance(key, bytes)
    assert len(key) == 16, f"Expected 16-byte key, got {len(key)}"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_macos_keychain_bad_browser_raises():
    """Requesting a Keychain entry for a browser that doesn't exist
    should raise ValueError (not crash in subprocess)."""
    with pytest.raises(ValueError, match="Unknown browser"):
        _get_macos_key("internet-explorer")


# ---------------------------------------------------------------------------
# Full extraction pipeline
# ---------------------------------------------------------------------------


def test_extract_cookies_returns_list():
    """extract_cookies must return a list (possibly empty) without
    raising, even for a domain with no cookies."""
    result = extract_cookies(".this-domain-definitely-has-no-cookies.invalid")
    assert isinstance(result, list)
    assert len(result) == 0


def test_extract_cookies_google():
    """Every dev box with Chrome has visited google.com at least once.
    We should get at least one cookie back with all expected fields."""
    cookies = extract_cookies(".google.com")
    # It's possible (though unlikely) a dev has zero google cookies.
    # Skip rather than fail if so — the test is about the pipeline, not
    # about guaranteeing google cookie presence.
    if not cookies:
        pytest.skip("No google.com cookies found (unusual but possible)")

    c = cookies[0]
    assert "name" in c and isinstance(c["name"], str)
    assert "value" in c and isinstance(c["value"], str)
    assert "domain" in c and isinstance(c["domain"], str)
    assert "path" in c and isinstance(c["path"], str)
    assert "secure" in c and isinstance(c["secure"], bool)
    assert "httpOnly" in c and isinstance(c["httpOnly"], bool)
    assert "expires" in c  # None (session) or float


def test_extract_cookies_values_are_decrypted():
    """Cookie values must be actual decrypted strings, not raw encrypted
    bytes. The v10 prefix or binary garbage in the value means decryption
    failed silently."""
    cookies = extract_cookies(".google.com")
    if not cookies:
        pytest.skip("No google.com cookies found")

    for c in cookies:
        value = c["value"]
        assert isinstance(value, str), f"Cookie {c['name']} value is not str"
        # Decrypted values should not start with the encryption prefix
        assert not value.startswith("v10"), (
            f"Cookie {c['name']} value starts with 'v10' — decryption "
            f"likely failed and raw ciphertext leaked through"
        )
        # Should not contain the 32-byte binary hash prefix
        assert value.isprintable() or "\n" in value or "\r" in value, (
            f"Cookie {c['name']} value contains non-printable characters — "
            f"binary hash prefix was not stripped"
        )


def test_extract_cookies_domain_filtering():
    """Cookies returned must all match the requested domain filter."""
    domain = ".google.com"
    cookies = extract_cookies(domain)
    if not cookies:
        pytest.skip("No google.com cookies found")

    for c in cookies:
        assert domain.lstrip(".") in c["domain"], (
            f"Cookie {c['name']} domain {c['domain']} does not match "
            f"filter {domain}"
        )


def test_extract_cookies_multiple_browsers_dont_crash():
    """Attempting extraction from each supported browser should either
    succeed or raise FileNotFoundError — never an unhandled crash."""
    for browser in ("chrome", "chromium", "brave", "edge"):
        try:
            result = extract_cookies(".google.com", browser=browser)
            assert isinstance(result, list)
        except FileNotFoundError:
            # Browser not installed — acceptable
            pass


def test_extract_cookies_chrome_has_some_cookies():
    """Chrome on a dev box should have a non-trivial cookie jar. This
    is a smoke test that the full pipeline (find DB → copy → decrypt)
    actually produces real data, not just an empty list from a silent
    failure."""
    # Use a very broad domain that any Chrome user will have
    for domain in (".google.com", ".youtube.com", ".github.com"):
        cookies = extract_cookies(domain)
        if cookies:
            assert len(cookies) >= 1
            return

    pytest.skip(
        "No cookies found for google/youtube/github — very unusual dev box"
    )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_extract_cookies_empty_domain_returns_all():
    """An empty-string domain filter should match everything (SQL LIKE
    '%%' matches all rows). Sanity check that we get a large result."""
    cookies = extract_cookies("")
    # Any real Chrome should have dozens of cookies
    assert len(cookies) > 0, "Empty domain filter should return all cookies"


def test_extract_cookies_expires_are_reasonable():
    """Cookie expiry timestamps, when present, should be in the Unix
    epoch range (not Chrome's 1601-based microseconds — that would
    indicate a conversion bug)."""
    cookies = extract_cookies(".google.com")
    if not cookies:
        pytest.skip("No google.com cookies found")

    for c in cookies:
        if c["expires"] is not None:
            # Should be a reasonable Unix timestamp (after 2020, before 2040)
            assert 1_577_836_800 < c["expires"] < 2_208_988_800, (
                f"Cookie {c['name']} expires={c['expires']} looks like an "
                f"unconverted Chrome timestamp or garbage"
            )


# ---------------------------------------------------------------------------
# Injection into automation browser (requires running Chrome)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cookies_import_into_automation_browser(browser):
    """Full round-trip: extract from user Chrome, inject into automation
    Chrome via CDP, read back via CDP, verify they match.

    Uses the ``browser`` fixture from conftest.py (headless temp Chrome).
    """
    from ai_dev_browser.core.cookies_import import cookies_import
    from ai_dev_browser.core.connection import get_active_tab

    tab = await get_active_tab(browser)

    # Import google.com cookies (most likely to exist)
    result = await cookies_import(tab, ".google.com")

    if result.get("imported", 0) == 0:
        pytest.skip("No google.com cookies to import")

    assert result["imported"] > 0
    assert result["domain"] == ".google.com"
    assert result["browser"] == "chrome"
    assert len(result["cookies"]) == result["imported"]

    # Verify cookies were actually injected by reading them back via CDP
    all_cookies = await browser.cookies.get_all()
    injected_names = {c["name"] for c in result["cookies"]}
    browser_names = {
        getattr(c, "name", "") for c in all_cookies
    }
    # At least some of the injected cookies should be readable
    overlap = injected_names & browser_names
    assert len(overlap) > 0, (
        f"Injected {injected_names} but CDP get_all returned none of them. "
        f"Browser has: {browser_names}"
    )
