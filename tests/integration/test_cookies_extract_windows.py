"""Regression: Windows path of cookies_extract.

The original cookies_import.py was author-tested on macOS only. On
Windows, three bugs blocked the entire pipeline:

  C. `_dpapi_decrypt` built a ctypes DataBlob via
     `ctypes.cast(create_string_buffer(...), c_void_p)` and passed it
     as a constructor arg. Empirically: 3-byte inputs worked, but the
     real 288-byte encrypted_key (from Chrome's Local State) triggered
     `OverflowError: int too long to convert` deterministically. Fix:
     use `ctypes.addressof()` on a reference-held buffer.

  D. Chrome on Windows holds `Cookies` with FILE_SHARE_NONE, so
     `shutil.copy2()` raises PermissionError as long as Chrome is
     running. macOS / Linux Chrome doesn't lock this strictly, which
     is why the macOS-only test pass missed this. Fix: catch on
     Windows and raise a clear, actionable RuntimeError.

  E. Modern Chrome (>= 96) moved Cookies under a `Network/` subdir.
     The original `_find_cookie_db()` only looked at `Profile X/Cookies`,
     missing every modern install.

Also covered: SHA256 prefix strip parity with Linux path (real
plaintext cookies don't start with 32 bytes of high-entropy bytes);
v20 (Chrome 127+ App-Bound Encryption) is documented as unsupported
but no longer silently lost — a logger warning surfaces the count.
"""

import os
import sys

import pytest

from ai_dev_browser.core.cookies_import import (
    _dpapi_decrypt,
    _find_cookie_db,
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
    if sys.platform != "win32":
        pytest.skip("Windows-specific regression suite")


def test_find_cookie_db_resolves_modern_chrome_network_path():
    """Bug E regression: Chrome >= 96 keeps Cookies under Profile/Network/.
    The original code only searched Profile/Cookies and failed with
    FileNotFoundError on every modern Chrome install."""
    try:
        path = _find_cookie_db("chrome")
    except FileNotFoundError:
        pytest.skip("No Chrome install on this CI/dev box")
    # Modern Chrome → .../Profile X/Network/Cookies. We accept either
    # the legacy or modern path; the fix is "doesn't crash with
    # FileNotFoundError when only the modern layout exists".
    assert path.name == "Cookies"
    assert path.parent.name in (
        "Network",
        "Default",
        "Profile 1",
        "Profile 2",
        "Profile 3",
    )


def test_dpapi_decrypt_handles_realistic_key_size():
    """Bug C regression: the original ctypes pattern silently worked
    on small inputs but threw `OverflowError: int too long to convert`
    on realistic 288-byte encrypted keys. Verify the addressof fix
    survives a non-toy payload.

    We can't decrypt a foreign payload (DPAPI is keyed to the current
    user), so we round-trip our own: encrypt some data via DPAPI via
    a tightly-typed CryptProtectData (test fixture must also pin
    argtypes — same hazard), then decrypt back via the function under
    test and verify the bytes match."""
    import base64
    import ctypes
    from ctypes import wintypes

    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.c_void_p)]

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

    # Build a ~300-byte plaintext to match real Chrome key size class
    plaintext = base64.b64encode(b"ai-dev-browser regression payload " * 8)[:300]
    assert len(plaintext) == 300

    in_buf = ctypes.create_string_buffer(plaintext, len(plaintext))
    in_blob = DataBlob(len(plaintext), ctypes.addressof(in_buf))
    out_blob = DataBlob()
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    )
    assert ok, f"CryptProtectData failed: GetLastError={kernel32.GetLastError()}"
    encrypted = ctypes.string_at(out_blob.pbData, out_blob.cbData)
    kernel32.LocalFree(out_blob.pbData)
    assert len(encrypted) > 100, "DPAPI ciphertext should be substantial"

    # The function under test. Pre-fix this raised on realistic sizes.
    decrypted = _dpapi_decrypt(encrypted)
    assert decrypted == plaintext, (
        "DPAPI round-trip mismatch — the addressof fix may have regressed"
    )


def test_locked_cookies_db_raises_clear_runtime_error(tmp_path):
    """Bug D regression: when Chrome holds the DB with FILE_SHARE_NONE,
    shutil.copy2 raises PermissionError. The fix repackages this as a
    RuntimeError that explicitly tells the caller to close Chrome.

    Simulate the lock by opening a temp file with no sharing — same
    effect as Chrome's hold. Point _find_cookie_db at it via a monkey
    patch so we exercise the production code path."""
    import ctypes
    import importlib
    from ctypes import wintypes
    from pathlib import Path

    # `from ai_dev_browser.core import cookies_import` collides with
    # the function of the same name re-exported there — pull the module
    # explicitly.
    cookies_mod = importlib.import_module("ai_dev_browser.core.cookies_import")

    # Create a fake "Cookies" file and lock it
    fake_db = tmp_path / "Cookies"
    fake_db.write_bytes(b"SQLite-ish bytes; not a real DB")

    GENERIC_READ = 0x80000000
    OPEN_EXISTING = 3
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

    # FILE_SHARE_NONE=0 → exclusive lock, matches Chrome's behavior
    locked = k32.CreateFileW(
        str(fake_db), GENERIC_READ, 0, None, OPEN_EXISTING, 0, None
    )
    INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
    assert locked and locked != INVALID_HANDLE_VALUE, "Could not lock test file"

    try:
        # Point cookie lookup at the locked file
        def fake_finder(_browser: str) -> Path:
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
