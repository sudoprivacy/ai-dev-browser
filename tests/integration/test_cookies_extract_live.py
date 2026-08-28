"""`cookies_extract_live` round-trip against a real (headless) Chrome.

The live path is the answer to the two systemic failures of the on-disk path
(`cookies_extract_offline`): in-memory session cookies that never hit disk, and
Chrome 127+ App-Bound (v20) cookies that a standalone process can't decrypt.
Both are moot here because we read the running browser's already-decrypted
store over CDP (`Storage.getCookies`) — so this test seeds cookies straight
into that store and reads them back.

What it proves, using only CDP (no dev-box browser, no OS key material, runs on
a clean CI runner via the headless `browser` fixture):
  * full values come back (not the truncated preview the old cookies_list gave)
  * httpOnly cookies ARE returned — the auth/session ones `document.cookie`
    can't see, which is the whole reason to prefer this over a js_evaluate read
  * a session cookie (no expiry) reports expires=None, matching the offline
    path's shape so the two extractors are interchangeable
  * the domain filter is a substring match, same semantics as offline
"""

from __future__ import annotations

import os

import pytest

from ai_dev_browser.cdp import network as cdp_network, storage
from ai_dev_browser.core.connection import get_active_tab
from ai_dev_browser.core.cookies import cookies_extract_live


SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)


@pytest.fixture(autouse=True)
def _integration_guard():
    if SKIP_INTEGRATION:
        pytest.skip("SKIP_INTEGRATION is set")


async def _seed(browser, params: list[cdp_network.CookieParam]) -> None:
    """Inject cookies straight into the live browser's store via CDP."""
    await browser.connection.send(storage.set_cookies(params), _is_update=True)


@pytest.mark.asyncio
async def test_reads_full_value_including_httponly_and_session(browser):
    tab = await get_active_tab(browser)
    await _seed(
        browser,
        [
            cdp_network.CookieParam(
                name="SID",
                value="live_secret_value_测试_longer_than_fifty_chars_0123456789",
                domain=".live.example",
                path="/",
                secure=True,
                http_only=True,  # invisible to document.cookie; must still come back
            )
        ],
    )

    cookies = await cookies_extract_live(tab, "live.example")
    by_name = {c["name"]: c for c in cookies}
    assert "SID" in by_name, f"seeded cookie not returned; got {by_name}"

    c = by_name["SID"]
    # Full value, not the 50-char truncated preview the retired cookies_list gave.
    assert c["value"] == "live_secret_value_测试_longer_than_fifty_chars_0123456789"
    assert c["domain"] == ".live.example"
    assert c["path"] == "/"
    assert c["secure"] is True
    assert c["httpOnly"] is True
    assert c["expires"] is None  # no expiry set -> session cookie


@pytest.mark.asyncio
async def test_domain_filter_is_substring_and_empty_returns_all(browser):
    tab = await get_active_tab(browser)
    await _seed(
        browser,
        [
            cdp_network.CookieParam(
                name="a", value="1", domain=".keep.example", path="/"
            ),
            cdp_network.CookieParam(
                name="b", value="2", domain="sub.keep.example", path="/"
            ),
            cdp_network.CookieParam(
                name="c", value="3", domain=".other.example", path="/"
            ),
        ],
    )

    kept = {c["name"] for c in await cookies_extract_live(tab, "keep.example")}
    assert kept == {"a", "b"}, f"substring filter wrong: {kept}"

    # "" returns every cookie — same semantics as cookies_extract_offline("").
    all_names = {c["name"] for c in await cookies_extract_live(tab, "")}
    assert {"a", "b", "c"} <= all_names


@pytest.mark.asyncio
async def test_no_match_returns_empty_list(browser):
    tab = await get_active_tab(browser)
    result = await cookies_extract_live(tab, ".definitely-not-present.invalid")
    assert result == []
