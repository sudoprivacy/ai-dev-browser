"""End-to-end: cookies_extract Windows path, against a fabricated Chrome profile.

Rather than monkeypatching individual helpers, we fabricate the EXACT
file layout that cookies_extract reads in production:

  <profile_root>/
    Local State              JSON with DPAPI-encrypted AES-256 key
    Default/Network/Cookies  SQLite DB with v10-encrypted cookie rows

Fabrication path (all real Windows APIs, no mocks):
  1. Generate a random 256-bit AES key.
  2. DPAPI-protect it via CryptProtectData (test fixture pins
     argtypes — same ctypes hazard the production decrypt path
     hit).
  3. Write `"DPAPI" || ciphertext` into Local State's
     os_crypt.encrypted_key (base64).
  4. AES-256-GCM-encrypt a known plaintext via Windows BCrypt
     (mirror of the production decrypt path).
  5. Format the blob as `v10 || nonce(12) || ciphertext || tag(16)`
     and INSERT it into a Chrome-schema SQLite DB.

Then we point _BROWSER_PATHS["win32"]["chrome"] at our fake profile
root and call the REAL `cookies_extract()` — no internal
monkeypatching. Every byte the production code reads, including
the DPAPI ciphertext that triggered Bug C and the modern
`Network/` subdir that triggered Bug E, comes from our fabrication.

A single passing run proves all of these layers work together:
  * Bug C — DPAPI ctypes addressof on ~288-byte encrypted key
  * Bug E — Profile/Network/Cookies modern layout discovery
  * SHA256 domain-binding prefix is stripped from decrypted values
  * AES-GCM Windows BCrypt decrypt (every byte goes through it)
  * SQLite text_factory=bytes + host_key LIKE matching
  * Returned dict shape: name/value/domain/path/secure/httpOnly/expires

The locked-DB test stays separate — the PermissionError path
isn't reachable through happy-path fabrication, so we still
simulate Chrome's FILE_SHARE_NONE hold with CreateFileW.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import importlib
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest


SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)


@pytest.fixture(autouse=True)
def _integration_guard():
    if SKIP_INTEGRATION:
        pytest.skip("SKIP_INTEGRATION is set")
    if sys.platform != "win32":
        pytest.skip("Windows-specific e2e — production uses DPAPI + BCrypt")


# ---------------------------------------------------------------------------
# Windows crypto helpers — fixture-side mirror of the production decrypt
# paths. Production decrypts; fixture encrypts. Same ctypes shape so any
# fixture bug surfaces as a clear test failure, not a confusing CI red.
# ---------------------------------------------------------------------------


def _dpapi_protect(plaintext: bytes) -> bytes:
    """CryptProtectData with the SAME argtype-pinning the production
    decrypt path uses. Returns the raw DPAPI ciphertext (without the
    "DPAPI" prefix — caller prepends if writing to Local State)."""
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.c_void_p)]

    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    in_buf = ctypes.create_string_buffer(plaintext, len(plaintext))
    in_blob = DataBlob(len(plaintext), ctypes.addressof(in_buf))
    out_blob = DataBlob()
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    )
    if not ok:
        raise OSError(f"CryptProtectData failed: {kernel32.GetLastError()}")
    ciphertext = ctypes.string_at(out_blob.pbData, out_blob.cbData)
    kernel32.LocalFree(out_blob.pbData)
    return ciphertext


def _bcrypt_aes_gcm_encrypt(
    key: bytes, nonce: bytes, plaintext: bytes
) -> tuple[bytes, bytes]:
    """AES-256-GCM encrypt via Windows BCrypt. Returns (ciphertext, tag).

    Mirror of production's `_decrypt_aes_gcm_windows`: same algorithm
    handle, same ChainingModeGCM property, same AuthInfo layout — only
    swap BCryptDecrypt for BCryptEncrypt and capture the tag the API
    writes out instead of validating an existing one."""
    bcrypt = ctypes.windll.bcrypt  # type: ignore[attr-defined]

    alg_handle = ctypes.c_void_p()
    status = bcrypt.BCryptOpenAlgorithmProvider(
        ctypes.byref(alg_handle),
        "AES".encode("utf-16-le") + b"\x00\x00",
        None,
        0,
    )
    if status != 0:
        raise OSError(f"BCryptOpenAlgorithmProvider failed: 0x{status:08x}")

    prop = "ChainingMode".encode("utf-16-le") + b"\x00\x00"
    mode = "ChainingModeGCM".encode("utf-16-le") + b"\x00\x00"
    bcrypt.BCryptSetProperty(alg_handle, prop, mode, len(mode), 0)

    key_handle = ctypes.c_void_p()
    bcrypt.BCryptGenerateSymmetricKey(
        alg_handle, ctypes.byref(key_handle), None, 0, key, len(key), 0
    )

    class AuthInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("dwInfoVersion", ctypes.c_ulong),
            ("pbNonce", ctypes.c_void_p),
            ("cbNonce", ctypes.c_ulong),
            ("pbAuthData", ctypes.c_void_p),
            ("cbAuthData", ctypes.c_ulong),
            ("pbTag", ctypes.c_void_p),
            ("cbTag", ctypes.c_ulong),
            ("pbMacContext", ctypes.c_void_p),
            ("cbMacContext", ctypes.c_ulong),
            ("cbAAD", ctypes.c_ulong),
            ("cbData", ctypes.c_ulonglong),
            ("dwFlags", ctypes.c_ulong),
        ]

    nonce_buf = ctypes.create_string_buffer(nonce, len(nonce))
    tag_buf = ctypes.create_string_buffer(16)

    auth_info = AuthInfo()
    auth_info.cbSize = ctypes.sizeof(AuthInfo)
    auth_info.dwInfoVersion = 1
    auth_info.pbNonce = ctypes.addressof(nonce_buf)
    auth_info.cbNonce = len(nonce)
    auth_info.pbTag = ctypes.addressof(tag_buf)
    auth_info.cbTag = 16

    out_buf = ctypes.create_string_buffer(len(plaintext))
    out_len = ctypes.c_ulong(0)

    status = bcrypt.BCryptEncrypt(
        key_handle,
        plaintext,
        len(plaintext),
        ctypes.byref(auth_info),
        None,
        0,
        out_buf,
        len(out_buf),
        ctypes.byref(out_len),
        0,
    )
    bcrypt.BCryptDestroyKey(key_handle)
    bcrypt.BCryptCloseAlgorithmProvider(alg_handle, 0)
    if status != 0:
        raise OSError(f"BCryptEncrypt failed: 0x{status:08x}")

    return out_buf.raw[: out_len.value], tag_buf.raw[:16]


def _fabricate_chrome_profile(
    profile_root: Path, cookies: list[dict], *, layout: str = "modern"
) -> None:
    """Write a Chrome profile dir indistinguishable from the real
    thing — Local State JSON with a DPAPI-protected AES key, and a
    Cookies SQLite DB with v10-encrypted blobs. `cookies` is a list
    of dicts with keys: host_key, name, plaintext, path (optional).

    `layout="modern"` puts the DB at Default/Network/Cookies (Chromium
    >= 96); `layout="legacy"` puts it at Default/Cookies (pre-96).
    Local State always lives at the user-data root."""
    aes_key = os.urandom(32)

    # Local State: "DPAPI" + DPAPI(aes_key), base64
    encrypted_key_with_prefix = b"DPAPI" + _dpapi_protect(aes_key)
    profile_root.mkdir(parents=True, exist_ok=True)
    (profile_root / "Local State").write_text(
        json.dumps(
            {
                "os_crypt": {
                    "encrypted_key": base64.b64encode(encrypted_key_with_prefix).decode(
                        "ascii"
                    )
                }
            }
        )
    )

    if layout == "modern":
        db_dir = profile_root / "Default" / "Network"
    elif layout == "legacy":
        db_dir = profile_root / "Default"
    else:
        raise ValueError(f"unknown layout: {layout!r}")
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "Cookies"

    conn = sqlite3.connect(str(db_path))
    try:
        # Minimal subset of Chrome's schema that satisfies cookies_extract's
        # SELECT — host_key, name, value, encrypted_value, path,
        # is_secure, is_httponly, expires_utc.
        conn.execute(
            "CREATE TABLE cookies ("
            "host_key TEXT NOT NULL, "
            "name TEXT NOT NULL, "
            "value TEXT NOT NULL DEFAULT '', "
            "encrypted_value BLOB NOT NULL DEFAULT '', "
            "path TEXT NOT NULL DEFAULT '/', "
            "is_secure INTEGER NOT NULL DEFAULT 0, "
            "is_httponly INTEGER NOT NULL DEFAULT 0, "
            "expires_utc INTEGER NOT NULL DEFAULT 0"
            ")"
        )
        for c in cookies:
            domain = c["host_key"]
            # Real Chrome prepends SHA256(domain) for domain-binding.
            # Production code strips this — verify the strip works.
            sha256_prefix = hashlib.sha256(domain.encode("utf-8")).digest()
            payload = sha256_prefix + c["plaintext"].encode("utf-8")
            nonce = os.urandom(12)
            ciphertext, tag = _bcrypt_aes_gcm_encrypt(aes_key, nonce, payload)
            blob = b"v10" + nonce + ciphertext + tag
            conn.execute(
                "INSERT INTO cookies (host_key, name, encrypted_value, path, "
                "is_secure, is_httponly, expires_utc) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    domain,
                    c["name"],
                    blob,
                    c.get("path", "/"),
                    int(c.get("secure", False)),
                    int(c.get("httponly", False)),
                    c.get("expires_utc", 0),
                ),
            )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# The actual e2e test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("layout", ["modern", "legacy"])
def test_cookies_extract_end_to_end_against_fabricated_profile(
    tmp_path, monkeypatch, layout
):
    """Single end-to-end test: fabricate a complete Chrome profile,
    run production cookies_extract, verify every layer of the
    Windows decrypt pipeline.

    Parametrized on layout because the user-data-dir resolution
    differs by 1 path component between modern (Network/) and legacy
    layouts — running both proves the conditional `if db_path.parent.name
    == "Network"` doesn't regress legacy callers."""
    cookies_mod = importlib.import_module("ai_dev_browser.core.cookies_import")

    domain = "example.com"
    plaintext_value = "session_token_abcdef0123456789_with_unicode_测试"

    profile_root = tmp_path / "FakeUserData"
    _fabricate_chrome_profile(
        profile_root,
        [
            {
                "host_key": domain,
                "name": "SID",
                "plaintext": plaintext_value,
                "secure": True,
                "httponly": True,
            },
            {
                # Subdomain match — host_key LIKE %example.com% must catch this
                "host_key": "sub." + domain,
                "name": "tracking",
                "plaintext": "different_value",
                "path": "/api",
            },
            {
                # Other domain — must NOT be returned
                "host_key": "other.test",
                "name": "noise",
                "plaintext": "should_not_appear",
            },
        ],
        layout=layout,
    )

    # Point the production path resolver at our fake profile. This is
    # the ONLY monkeypatch — every other byte cookies_extract reads
    # was produced by Windows crypto APIs on real fabricated input.
    monkeypatch.setitem(
        cookies_mod._BROWSER_PATHS["win32"],
        "chrome",
        [str(profile_root)],
    )

    result = cookies_mod.cookies_extract(domain=domain, browser="chrome")

    # Two cookies match `%example.com%`; the "other.test" cookie must not.
    assert len(result) == 2, (
        f"expected 2 cookies matching {domain!r}, got {len(result)}: {result}"
    )
    names = {c["name"]: c for c in result}
    assert set(names) == {"SID", "tracking"}, (
        f"unexpected names returned: {sorted(names)}"
    )

    sid = names["SID"]
    assert sid["value"] == plaintext_value, (
        f"plaintext mismatch — SHA256 strip / AES-GCM / DPAPI somewhere broke."
        f"\nexpected: {plaintext_value!r}\nactual:   {sid['value']!r}"
    )
    assert sid["domain"] == domain
    assert sid["path"] == "/"
    assert sid["secure"] is True
    assert sid["httpOnly"] is True
    assert sid["expires"] is None  # session cookie

    tracking = names["tracking"]
    assert tracking["value"] == "different_value"
    assert tracking["domain"] == "sub." + domain
    assert tracking["path"] == "/api"
    assert tracking["secure"] is False


def test_locked_cookies_db_raises_clear_runtime_error(tmp_path):
    """Bug D: when Chrome holds the DB with FILE_SHARE_NONE,
    `shutil.copy2` raises PermissionError. The fix repackages this as
    a RuntimeError that explicitly tells the caller to close Chrome.

    Lock simulation uses CreateFileW with share_mode=0 — same exclusive
    hold Chrome itself takes. Can't be reached via the e2e fabrication
    (that path is happy-path), so this stays a separate test."""
    from ctypes import wintypes

    cookies_mod = importlib.import_module("ai_dev_browser.core.cookies_import")

    fake_db = tmp_path / "Cookies"
    fake_db.write_bytes(b"placeholder; not parsed before lock-check fails")

    k32 = ctypes.windll.kernel32
    k32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CloseHandle.argtypes = [wintypes.HANDLE]

    locked = k32.CreateFileW(
        str(fake_db),
        0x80000000,
        0,
        None,
        3,
        0,
        None,  # GENERIC_READ, OPEN_EXISTING
    )
    INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
    assert locked and locked != INVALID_HANDLE_VALUE, "could not lock test file"

    try:

        def fake_finder(_browser: str, _user_data_dir: str | None = None) -> Path:
            return fake_db

        original = cookies_mod._find_cookie_db
        cookies_mod._find_cookie_db = fake_finder
        try:
            with pytest.raises(RuntimeError, match="while it is running"):
                cookies_mod.cookies_extract("anydomain")
        finally:
            cookies_mod._find_cookie_db = original
    finally:
        k32.CloseHandle(locked)
