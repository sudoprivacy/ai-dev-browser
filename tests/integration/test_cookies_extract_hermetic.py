"""`cookies_extract` pipeline, tested against a synthetic Chrome profile.

These tests build their own Chrome user-data directory — a Cookies SQLite with
known rows — and point `cookies_extract(user_data_dir=...)` at it. Nothing here
reads, locks, or depends on the developer's real browser.

That is the whole point. The suite this replaces read the developer's live
Chrome (`cookies_extract(".google.com")` and asserted on whatever was there),
so it failed two ways that have nothing to do with the code: on Windows the
running browser holds the Cookies file with an exclusive lock, and everywhere it
assumed the machine happened to have the right cookies. A test that passes or
fails based on what else is running on the box is not testing the code.

Decryption (DPAPI / Keychain / libsecret) is genuinely platform-bound and cannot
be exercised hermetically, so it is not attempted here — it lives in the opt-in
`test_cookies_import.py`. What *is* covered is everything around it:
database discovery, the lock-safe copy, WAL handling, the LIKE domain filter,
byte-column decoding, the 1601→1970 epoch conversion, and the returned shape —
all reachable through Chrome's plaintext `value` column, no key required.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ai_dev_browser.core.cookies_import import _find_cookie_db, cookies_extract

# Chrome stores expiry as microseconds since 1601-01-01. This is 2030-01-01,
# well inside the range the extractor sanity-checks after converting to Unix.
_CHROME_EXPIRES_2030 = 13_537_929_600_000_000
_UNIX_EXPIRES_2030 = 1_893_456_000


def _make_profile(tmp_path: Path, rows: list[dict], profile: str = "Default") -> str:
    """Write a synthetic Chrome user-data dir with a plaintext Cookies DB.

    Returns the user-data-dir path to hand to `cookies_extract`. Values go in
    the plaintext `value` column, so the read never needs a decryption key.
    """
    cookies_dir = tmp_path / profile / "Network"
    cookies_dir.mkdir(parents=True, exist_ok=True)
    db = cookies_dir / "Cookies"

    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            """CREATE TABLE cookies (
                host_key TEXT, name TEXT, value TEXT, encrypted_value BLOB,
                path TEXT, is_secure INTEGER, is_httponly INTEGER,
                expires_utc INTEGER
            )"""
        )
        conn.executemany(
            "INSERT INTO cookies (host_key, name, value, encrypted_value, path, "
            "is_secure, is_httponly, expires_utc) VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    r["host"],
                    r["name"],
                    r.get("value", ""),
                    r.get("encrypted", b""),
                    r.get("path", "/"),
                    int(r.get("secure", 0)),
                    int(r.get("httponly", 0)),
                    r.get("expires", _CHROME_EXPIRES_2030),
                )
                for r in rows
            ],
        )
        conn.commit()
    finally:
        conn.close()
    return str(tmp_path)


def test_returns_matching_cookies_with_full_shape(tmp_path):
    udd = _make_profile(
        tmp_path,
        [
            {
                "host": ".example.com",
                "name": "session",
                "value": "abc123",
                "secure": 1,
                "httponly": 1,
            }
        ],
    )
    cookies = cookies_extract(".example.com", user_data_dir=udd)

    assert len(cookies) == 1
    c = cookies[0]
    assert c["name"] == "session"
    assert c["value"] == "abc123"
    assert c["domain"] == ".example.com"
    assert c["path"] == "/"
    assert c["secure"] is True
    assert c["httpOnly"] is True
    assert c["expires"] == pytest.approx(_UNIX_EXPIRES_2030, abs=1)


def test_domain_filter_is_a_substring_match(tmp_path):
    udd = _make_profile(
        tmp_path,
        [
            {"host": ".example.com", "name": "keep", "value": "1"},
            {"host": ".other.com", "name": "drop", "value": "2"},
            {"host": "sub.example.com", "name": "keep_sub", "value": "3"},
        ],
    )
    names = {c["name"] for c in cookies_extract("example.com", user_data_dir=udd)}
    assert names == {"keep", "keep_sub"}


def test_empty_domain_returns_everything(tmp_path):
    udd = _make_profile(
        tmp_path,
        [
            {"host": ".a.com", "name": "x", "value": "1"},
            {"host": ".b.com", "name": "y", "value": "2"},
        ],
    )
    assert len(cookies_extract("", user_data_dir=udd)) == 2


def test_no_match_returns_empty_list_without_raising(tmp_path):
    udd = _make_profile(tmp_path, [{"host": ".a.com", "name": "x", "value": "1"}])
    result = cookies_extract(".nonexistent.invalid", user_data_dir=udd)
    assert result == []


def test_session_cookie_has_null_expiry(tmp_path):
    udd = _make_profile(
        tmp_path,
        [{"host": ".a.com", "name": "s", "value": "1", "expires": 0}],
    )
    assert cookies_extract(".a.com", user_data_dir=udd)[0]["expires"] is None


def test_legacy_profile_root_layout_is_found(tmp_path):
    """Pre-Chromium-96 kept Cookies at the profile root, not under Network/."""
    (tmp_path / "Default").mkdir(parents=True)
    db = tmp_path / "Default" / "Cookies"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT, "
            "encrypted_value BLOB, path TEXT, is_secure INTEGER, "
            "is_httponly INTEGER, expires_utc INTEGER)"
        )
        conn.execute("INSERT INTO cookies VALUES ('.a.com','legacy','v',x'','/',0,0,0)")
        conn.commit()
    finally:
        conn.close()

    cookies = cookies_extract(".a.com", user_data_dir=str(tmp_path))
    assert cookies[0]["name"] == "legacy"


def test_all_plaintext_read_never_fetches_a_key(tmp_path, monkeypatch):
    """Lazy key retrieval: a domain served entirely from plaintext must never
    reach into the platform keystore (no Keychain prompt, no DPAPI, no
    libsecret) — and must not fail when that material is unavailable."""

    def _boom(*a, **k):
        raise AssertionError("platform key must not be fetched for plaintext cookies")

    # The submodule `cookies_import` and the function it exports share a name,
    # and the package re-exports the function — so every attribute-walk to
    # `ai_dev_browser.core.cookies_import` (incl. monkeypatch's dotted form)
    # lands on the function. sys.modules holds the real module under its full
    # name regardless.
    import sys

    mod = sys.modules["ai_dev_browser.core.cookies_import"]
    monkeypatch.setattr(mod, "_platform_keys", _boom)

    udd = _make_profile(tmp_path, [{"host": ".a.com", "name": "p", "value": "plain"}])
    assert cookies_extract(".a.com", user_data_dir=udd)[0]["value"] == "plain"


def test_missing_user_data_dir_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        cookies_extract(".a.com", user_data_dir=str(tmp_path / "nope"))


def test_unknown_browser_name_raises_not_silently_returns(tmp_path):
    """A made-up browser must raise, not return a bogus path. Hermetic: a name
    that matches no platform install can never resolve, no real Chrome needed."""
    with pytest.raises((FileNotFoundError, ValueError)):
        _find_cookie_db("netscape-navigator-4")
