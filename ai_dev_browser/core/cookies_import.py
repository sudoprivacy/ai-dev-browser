"""Import cookies from the user's regular browser into the automation browser.

Reads cookies directly from the browser's local SQLite database and injects
them via CDP Storage.setCookies. No external dependencies — uses only stdlib
modules plus platform-native crypto (macOS CommonCrypto, Windows DPAPI).

Reference implementation inspired by:
  https://github.com/borisbabic/browser_cookie3  (MIT license)
  https://github.com/thewh1teagle/rookie          (MIT license, archived)

Platform support:
  macOS  — Chrome, Chromium, Brave, Edge. Decrypts v10 cookies via
           Keychain + CommonCrypto (libcommonCrypto.dylib). A system
           dialog may prompt the user to authorize Keychain access.
  Windows — Chrome, Chromium, Brave, Edge. Decrypts v10 cookies via
            DPAPI (CryptUnprotectData). v20 cookies (Chrome 127+,
            App-Bound Encryption) are NOT supported — those require
            elevated privileges and reverse-engineering Chrome's
            Elevation Service. Affected cookies are silently skipped.
  Linux  — Chrome, Chromium, Brave. Decrypts v10/v11 cookies via
           PBKDF2 with the password from libsecret (if available)
           or the Chromium fallback password "peanuts".
"""

from __future__ import annotations

import ctypes
import ctypes.util
import hashlib
import json
import logging
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from ._tab import Tab

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Browser profile paths (Chrome-family)
# ---------------------------------------------------------------------------

_BROWSER_PATHS: dict[str, dict[str, list[str]]] = {
    "darwin": {
        "chrome": ["~/Library/Application Support/Google/Chrome"],
        "chromium": ["~/Library/Application Support/Chromium"],
        "brave": ["~/Library/Application Support/BraveSoftware/Brave-Browser"],
        "edge": ["~/Library/Application Support/Microsoft Edge"],
    },
    "win32": {
        "chrome": ["~/AppData/Local/Google/Chrome/User Data"],
        "chromium": ["~/AppData/Local/Chromium/User Data"],
        "brave": ["~/AppData/Local/BraveSoftware/Brave-Browser/User Data"],
        "edge": ["~/AppData/Local/Microsoft/Edge/User Data"],
    },
    "linux": {
        "chrome": ["~/.config/google-chrome"],
        "chromium": ["~/.config/chromium"],
        "brave": ["~/.config/BraveSoftware/Brave-Browser"],
        "edge": ["~/.config/microsoft-edge"],
    },
}

# Keychain service names per browser (macOS)
_KEYCHAIN_SERVICE: dict[str, str] = {
    "chrome": "Chrome Safe Storage",
    "chromium": "Chromium Safe Storage",
    "brave": "Brave Safe Storage",
    "edge": "Microsoft Edge Safe Storage",
}

# DPAPI Local State file key prefix
_DPAPI_KEY_PREFIX = b"DPAPI"


# ---------------------------------------------------------------------------
# Platform-specific decryption
# ---------------------------------------------------------------------------


def _get_macos_key(browser: str) -> bytes:
    """Retrieve the browser encryption key from macOS Keychain.

    Calls /usr/bin/security to read the safe-storage password, then
    derives a 16-byte AES key via PBKDF2-SHA1 (1003 iterations,
    salt='saltysalt').
    """
    service = _KEYCHAIN_SERVICE.get(browser)
    if not service:
        raise ValueError(f"Unknown browser for macOS Keychain: {browser}")

    # -w outputs just the password value
    result = subprocess.run(
        [
            "/usr/bin/security",
            "-q",
            "find-generic-password",
            "-w",
            "-s",
            service,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to get {service} password from Keychain "
            f"(exit {result.returncode}). You may need to click 'Allow' "
            f"in the Keychain dialog."
        )

    password = result.stdout.strip()
    return hashlib.pbkdf2_hmac(
        "sha1", password.encode("utf-8"), b"saltysalt", 1003, dklen=16
    )


def _decrypt_aes_cbc_macos(key: bytes, ciphertext: bytes) -> str:
    """AES-128-CBC decrypt via macOS CommonCrypto (zero external deps).

    On modern macOS (11+), CommonCrypto lives inside the dyld shared
    cache via libSystem.B.dylib rather than as a standalone dylib.
    """
    # Modern macOS: CCCrypt is re-exported through libSystem
    lib_path = ctypes.util.find_library("CommonCrypto")
    if lib_path:
        lib = ctypes.cdll.LoadLibrary(lib_path)
    else:
        lib = ctypes.cdll.LoadLibrary("/usr/lib/libSystem.B.dylib")

    iv = b" " * 16  # Chromium uses 16 spaces as IV

    # CCCrypt(op, alg, options, key, keyLen, iv, dataIn, dataInLen, dataOut,
    #         dataOutAvailable, dataOutMoved)
    # kCCDecrypt=1, kCCAlgorithmAES128=0, kCCOptionPKCS7Padding=1
    out_buf = ctypes.create_string_buffer(len(ciphertext) + 16)
    out_len = ctypes.c_size_t(0)

    status = lib.CCCrypt(
        ctypes.c_uint32(1),  # kCCDecrypt
        ctypes.c_uint32(0),  # kCCAlgorithmAES128
        ctypes.c_uint32(1),  # kCCOptionPKCS7Padding
        key,
        ctypes.c_size_t(len(key)),
        iv,
        ciphertext,
        ctypes.c_size_t(len(ciphertext)),
        out_buf,
        ctypes.c_size_t(len(out_buf)),
        ctypes.byref(out_len),
    )
    if status != 0:
        raise RuntimeError(f"CCCrypt failed with status {status}")

    decrypted = out_buf.raw[: out_len.value]

    # Chromium >= 24 prepends a 32-byte SHA256 hash of the domain to the
    # cookie value for integrity checks. Strip it if present: real cookie
    # values are always printable ASCII/UTF-8, so if the first 32 bytes
    # contain non-printable characters, they are the hash prefix.
    if len(decrypted) > 32 and not decrypted[:32].isascii():
        decrypted = decrypted[32:]

    return decrypted.decode("utf-8", errors="replace")


def _get_windows_key(browser_data_dir: Path) -> bytes:
    """Read the AES-GCM key from Chrome's Local State file (Windows DPAPI)."""
    local_state_path = browser_data_dir / "Local State"
    if not local_state_path.exists():
        raise FileNotFoundError(f"Local State not found: {local_state_path}")

    with open(local_state_path, "r", encoding="utf-8") as f:
        local_state = json.load(f)

    import base64

    encrypted_key_b64 = local_state["os_crypt"]["encrypted_key"]
    encrypted_key = base64.b64decode(encrypted_key_b64)

    # Strip the "DPAPI" prefix
    if not encrypted_key.startswith(_DPAPI_KEY_PREFIX):
        raise ValueError("Encrypted key does not start with DPAPI prefix")
    encrypted_key = encrypted_key[len(_DPAPI_KEY_PREFIX) :]

    # Decrypt via DPAPI
    return _dpapi_decrypt(encrypted_key)


def _dpapi_decrypt(encrypted: bytes) -> bytes:
    """Decrypt data using Windows DPAPI (CryptUnprotectData).

    The previous implementation built the DataBlob by wrapping the
    string buffer in `ctypes.cast(..., c_void_p)` and passing it as a
    constructor argument. On 64-bit Windows, ctypes was rejecting
    realistic-sized payloads (288-byte encrypted_key after stripping
    "DPAPI" prefix) with `OverflowError: int too long to convert` —
    the cast result's int conversion path appears to be size-dependent.
    Empirically: 3-byte input worked, 288-byte input failed every time.

    Fix: get the buffer's address as a plain Python int via
    `ctypes.addressof()`, hold a reference to the buffer for the
    duration of the syscall so it isn't GC'd, and assign to the
    `c_void_p` field directly.
    """

    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.c_void_p)]

    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

    # Pin argtypes so ctypes doesn't auto-guess pointer types — the
    # original failure mode was a buffer-size-dependent OverflowError
    # because address conversions defaulted to signed-int treatment.
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    input_buf = ctypes.create_string_buffer(encrypted, len(encrypted))
    input_blob = DataBlob(len(encrypted), ctypes.addressof(input_buf))
    output_blob = DataBlob()

    if not crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(output_blob),
    ):
        raise RuntimeError(
            f"CryptUnprotectData failed: GetLastError={kernel32.GetLastError()}"
        )

    result = ctypes.string_at(output_blob.pbData, output_blob.cbData)
    kernel32.LocalFree(output_blob.pbData)
    return result


def _decrypt_aes_gcm_windows(key: bytes, ciphertext: bytes) -> str:
    """AES-256-GCM decrypt for Windows Chrome v10 cookies.

    The encrypted value layout is: 'v10' (already stripped) +
    nonce (12 bytes) + ciphertext + tag (16 bytes).
    Uses Windows BCrypt API (bcrypt.dll) — zero external deps.
    """
    nonce = ciphertext[:12]
    tag = ciphertext[-16:]
    data = ciphertext[12:-16]

    # BCrypt AES-GCM decryption
    bcrypt = ctypes.windll.bcrypt  # type: ignore[attr-defined]

    # BCRYPT_AES_ALGORITHM = "AES"
    alg_handle = ctypes.c_void_p()
    bcrypt.BCryptOpenAlgorithmProvider(
        ctypes.byref(alg_handle),
        "AES".encode("utf-16-le") + b"\x00\x00",
        None,
        0,
    )

    # Set chaining mode to GCM
    prop = "ChainingMode".encode("utf-16-le") + b"\x00\x00"
    mode = "ChainingModeGCM".encode("utf-16-le") + b"\x00\x00"
    bcrypt.BCryptSetProperty(alg_handle, prop, mode, len(mode), 0)

    # Generate key object
    key_handle = ctypes.c_void_p()
    bcrypt.BCryptGenerateSymmetricKey(
        alg_handle, ctypes.byref(key_handle), None, 0, key, len(key), 0
    )

    # BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO structure
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

    nonce_buf = ctypes.create_string_buffer(nonce)
    tag_buf = ctypes.create_string_buffer(tag)

    auth_info = AuthInfo()
    auth_info.cbSize = ctypes.sizeof(AuthInfo)
    auth_info.dwInfoVersion = 1
    auth_info.pbNonce = ctypes.cast(nonce_buf, ctypes.c_void_p)
    auth_info.cbNonce = len(nonce)
    auth_info.pbTag = ctypes.cast(tag_buf, ctypes.c_void_p)
    auth_info.cbTag = len(tag)

    out_buf = ctypes.create_string_buffer(len(data))
    out_len = ctypes.c_ulong(0)

    status = bcrypt.BCryptDecrypt(
        key_handle,
        data,
        len(data),
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
        raise RuntimeError(f"BCryptDecrypt failed with status 0x{status:08x}")

    decrypted = out_buf.raw[: out_len.value]
    # Modern Chromium (114+, when "Encrypted Cookies" feature shipped)
    # prepends a 32-byte SHA256 hash of the cookie's eTLD+1 domain to
    # bind the value to its origin. The Linux path strips this; the
    # Windows path didn't, leaving 32 bytes of binary garbage at the
    # head of every decrypted cookie value. Detect heuristically:
    # plaintext cookies are virtually always printable ASCII, so a
    # leading 32-byte chunk that isn't ASCII is the hash prefix.
    if len(decrypted) > 32 and not decrypted[:32].isascii():
        decrypted = decrypted[32:]
    return decrypted.decode("utf-8", errors="replace")


def _get_linux_password(browser: str) -> str:
    """Get the browser encryption password on Linux.

    Tries libsecret (GNOME Keyring) first, then falls back to the
    Chromium default password "peanuts".
    """
    try:
        import secretstorage

        connection = secretstorage.dbus_init()
        collection = secretstorage.get_default_collection(connection)
        if collection.is_locked():
            collection.unlock()

        schema = "chrome_libsecret_os_crypt_password_v2"
        attrs = {"application": browser}
        items = list(collection.search_items(attrs))

        if not items:
            # Try v1 schema
            schema = "chrome_libsecret_os_crypt_password_v1"
            items = list(collection.search_items({"xdg:schema": schema}))

        if items:
            return items[0].get_secret().decode("utf-8")
    except Exception:
        pass

    return "peanuts"


def _decrypt_linux(password: str, ciphertext: bytes) -> str:
    """AES-128-CBC decrypt for Linux Chrome cookies.

    Uses PBKDF2 with 1 iteration (Linux default) and the same IV/salt
    as macOS, then decrypts via OpenSSL libcrypto (available on all
    Linux distros).
    """
    key = hashlib.pbkdf2_hmac(
        "sha1", password.encode("utf-8"), b"saltysalt", 1, dklen=16
    )

    # Try to use libcrypto for AES-CBC
    libcrypto_name = ctypes.util.find_library("crypto")
    if not libcrypto_name:
        raise RuntimeError("libcrypto (OpenSSL) not found. Install openssl/libssl-dev.")

    libcrypto = ctypes.cdll.LoadLibrary(libcrypto_name)
    iv = b" " * 16

    # EVP_CIPHER_CTX_new, EVP_DecryptInit_ex, EVP_DecryptUpdate,
    # EVP_DecryptFinal_ex, EVP_CIPHER_CTX_free
    ctx = libcrypto.EVP_CIPHER_CTX_new()
    if not ctx:
        raise RuntimeError("EVP_CIPHER_CTX_new failed")

    try:
        cipher = libcrypto.EVP_aes_128_cbc()
        libcrypto.EVP_DecryptInit_ex(ctx, cipher, None, key, iv)

        out_buf = ctypes.create_string_buffer(len(ciphertext) + 16)
        out_len = ctypes.c_int(0)
        libcrypto.EVP_DecryptUpdate(
            ctx, out_buf, ctypes.byref(out_len), ciphertext, len(ciphertext)
        )
        total = out_len.value

        final_len = ctypes.c_int(0)
        libcrypto.EVP_DecryptFinal_ex(
            ctx,
            ctypes.cast(
                ctypes.addressof(out_buf) + total, ctypes.POINTER(ctypes.c_char)
            ),
            ctypes.byref(final_len),
        )
        total += final_len.value

        decrypted = out_buf.raw[:total]
        # Strip 32-byte SHA256 domain hash prefix (Chromium >= 24)
        if len(decrypted) > 32 and not decrypted[:32].isascii():
            decrypted = decrypted[32:]
        return decrypted.decode("utf-8", errors="replace")
    finally:
        libcrypto.EVP_CIPHER_CTX_free(ctx)


# ---------------------------------------------------------------------------
# Cookie extraction
# ---------------------------------------------------------------------------


def _find_cookie_db(browser: str) -> Path:
    """Locate the Cookies SQLite database for the given browser.

    Chromium >= 96 (~2021) moved Cookies into a `Network/` subdir of
    the profile (`Profile 1/Network/Cookies`); older versions kept it
    at the profile root (`Profile 1/Cookies`). Try the new location
    first, fall back to the legacy path.
    """
    plat = sys.platform
    if plat.startswith("linux"):
        plat = "linux"

    paths = _BROWSER_PATHS.get(plat, {}).get(browser, [])
    for base in paths:
        expanded = Path(base).expanduser()
        # Try Default first, then numbered Profiles. The "first hit
        # wins" pick is a known UX limitation when users have multiple
        # profiles — documented in the cookies_extract docstring.
        for profile in ["Default", "Profile 1", "Profile 2", "Profile 3"]:
            for subpath in ("Network/Cookies", "Cookies"):
                db = expanded / profile / subpath
                if db.exists():
                    return db

    raise FileNotFoundError(
        f"Could not find {browser} cookie database on {plat}. "
        f"Searched: {[str(Path(p).expanduser()) for p in paths]}"
    )


def _decrypt_cookie_value(
    encrypted_value: bytes,
    *,
    mac_key: bytes | None = None,
    win_key: bytes | None = None,
    linux_password: str | None = None,
) -> str | None:
    """Decrypt a single encrypted_value blob. Returns None on failure."""
    if not encrypted_value:
        return None

    plat = sys.platform

    if plat == "darwin":
        if not mac_key:
            return None
        # v10 prefix = Keychain-encrypted
        if encrypted_value[:3] == b"v10":
            try:
                return _decrypt_aes_cbc_macos(mac_key, encrypted_value[3:])
            except Exception:
                return None
        return None

    elif plat == "win32":
        if not win_key:
            return None
        # v10 = DPAPI + AES-GCM
        if encrypted_value[:3] == b"v10":
            try:
                return _decrypt_aes_gcm_windows(win_key, encrypted_value[3:])
            except Exception:
                return None
        # v20 = App-Bound Encryption (Chrome 127+) — not supported
        if encrypted_value[:3] == b"v20":
            return None
        # Legacy DPAPI (no version prefix)
        try:
            return _dpapi_decrypt(encrypted_value).decode("utf-8", errors="replace")
        except Exception:
            return None

    elif plat.startswith("linux"):
        # v10 or v11 prefix
        if encrypted_value[:3] in (b"v10", b"v11"):
            try:
                return _decrypt_linux(linux_password or "peanuts", encrypted_value[3:])
            except Exception:
                return None
        return None

    return None


def cookies_extract(
    domain: str,
    browser: str = "chrome",
) -> list[dict[str, Any]]:
    """Use when: you need to inspect what cookies a domain has in the
    user's real browser — without an automation browser. Returns a list
    of cookie dicts. Pair with `cookies_import` to inject into an
    automation session.

    Reads the browser's local SQLite cookie database and decrypts values
    using platform-native crypto APIs. No external dependencies required.

    A system dialog may appear on macOS asking to authorize Keychain access.
    This serves as implicit user consent for cookie extraction.

    Args:
        domain: Domain to filter cookies (e.g. ".grok.com", "github.com").
                Matches with SQL LIKE, so ".grok.com" matches subdomains.
        browser: Browser to read from. One of: "chrome", "chromium",
                 "brave", "edge". Default: "chrome".

    Returns:
        List of cookie dicts with keys: name, value, domain, path,
        secure, httpOnly, expires.

    Raises:
        FileNotFoundError: If the cookie database cannot be located.
        RuntimeError: If decryption key cannot be obtained.
    """
    db_path = _find_cookie_db(browser)

    # Copy the db to a temp file to avoid locking issues
    tmp_dir = tempfile.mkdtemp()
    tmp_db = Path(tmp_dir) / "Cookies"
    try:
        try:
            shutil.copy2(str(db_path), str(tmp_db))
        except PermissionError as e:
            # Windows-specific: Chrome holds the Cookies DB with
            # FILE_SHARE_NONE, so no other process can open it for
            # reading while Chrome is running with this profile. macOS
            # / Linux Chrome doesn't lock this aggressively — this
            # error path is essentially Windows-only.
            if sys.platform == "win32":
                raise RuntimeError(
                    f"Cannot read {browser}'s cookie database while it is "
                    "running (Windows holds the file with exclusive lock). "
                    "Close Chrome (or the matching profile window) and "
                    "retry. A future release may add DuplicateHandle-based "
                    "bypass to avoid this step."
                ) from e
            raise

        # Also copy WAL if present (for fresh cookies not yet checkpointed)
        wal_path = db_path.parent / "Cookies-wal"
        if wal_path.exists():
            try:
                shutil.copy2(str(wal_path), str(Path(tmp_dir) / "Cookies-wal"))
            except PermissionError:
                pass  # WAL is optional; missing it just means a stale read
        shm_path = db_path.parent / "Cookies-shm"
        if shm_path.exists():
            try:
                shutil.copy2(str(shm_path), str(Path(tmp_dir) / "Cookies-shm"))
            except PermissionError:
                pass

        # Get decryption key
        mac_key = None
        win_key = None
        linux_password = None

        if sys.platform == "darwin":
            mac_key = _get_macos_key(browser)
        elif sys.platform == "win32":
            # Local State lives at the User Data root, not the profile
            # dir. Layouts:
            #   Modern  (Chromium >= 96): UserData/Profile/Network/Cookies
            #                             → user_data_dir = parent[2]
            #   Legacy:                   UserData/Profile/Cookies
            #                             → user_data_dir = parent[1]
            # The previous fix to `_find_cookie_db` added the Network/
            # subdir but left this lookup at .parent.parent, which on
            # modern Chrome resolved to the profile dir and broke the
            # whole pipeline with FileNotFoundError on Local State.
            if db_path.parent.name == "Network":
                browser_data_dir = db_path.parent.parent.parent
            else:
                browser_data_dir = db_path.parent.parent
            win_key = _get_windows_key(browser_data_dir)
        elif sys.platform.startswith("linux"):
            linux_password = _get_linux_password(browser)

        # Query cookies. text_factory=bytes prevents sqlite3 from
        # attempting UTF-8 decode on BLOB columns (encrypted_value).
        conn = sqlite3.connect(str(tmp_db))
        conn.text_factory = bytes
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(
                "SELECT host_key, name, value, encrypted_value, path, "
                "is_secure, is_httponly, expires_utc "
                "FROM cookies WHERE host_key LIKE ?",
                (f"%{domain}%",),
            )

            cookies = []
            v20_skipped = 0
            for row in cursor:
                # text_factory=bytes means string columns come back as
                # bytes; decode them. encrypted_value stays as raw bytes.
                plaintext = row["value"]
                if isinstance(plaintext, bytes):
                    plaintext = plaintext.decode("utf-8", errors="replace")

                encrypted = row["encrypted_value"]

                # Prefer plaintext value; fall back to decrypted
                if plaintext:
                    value = plaintext
                elif encrypted:
                    value = _decrypt_cookie_value(
                        encrypted,
                        mac_key=mac_key,
                        win_key=win_key,
                        linux_password=linux_password,
                    )
                    # Track v20 (Chrome 127+ App-Bound Encryption) so
                    # caller knows how many cookies for this domain
                    # were silently dropped — otherwise "I got 3
                    # cookies when there should be 30" is mysterious.
                    if value is None and encrypted[:3] == b"v20":
                        v20_skipped += 1
                else:
                    value = None

                if value is None:
                    continue

                # Decode other byte columns
                host_key = row["host_key"]
                if isinstance(host_key, bytes):
                    host_key = host_key.decode("utf-8", errors="replace")
                name = row["name"]
                if isinstance(name, bytes):
                    name = name.decode("utf-8", errors="replace")
                path = row["path"]
                if isinstance(path, bytes):
                    path = path.decode("utf-8", errors="replace")

                # Chrome stores expiry as microseconds since 1601-01-01.
                # Convert to Unix epoch seconds.
                expires_utc = row["expires_utc"]
                if expires_utc and expires_utc > 0:
                    # Chrome epoch offset: 11644473600 seconds
                    expires_unix = (expires_utc / 1_000_000) - 11644473600
                else:
                    expires_unix = -1  # session cookie

                cookies.append(
                    {
                        "name": name,
                        "value": value,
                        "domain": host_key,
                        "path": path,
                        "secure": bool(row["is_secure"]),
                        "httpOnly": bool(row["is_httponly"]),
                        "expires": expires_unix if expires_unix > 0 else None,
                    }
                )

            if v20_skipped:
                logger.warning(
                    "%d cookie(s) for domain %r are v20 (Chrome 127+ "
                    "App-Bound Encryption) and could not be decrypted. "
                    "These are silently dropped from the result. If you "
                    "depend on a specific cookie that is missing, check "
                    "whether your Chrome version uses App-Bound — current "
                    "ai-dev-browser supports only v10/v11.",
                    v20_skipped,
                    domain,
                )
            return cookies
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


async def cookies_import(
    tab: Tab,
    domain: str,
    browser: str = "chrome",
) -> dict:
    """Use when: Cloudflare/Akamai blocks the automation browser — import
    auth cookies from the user's daily-driver browser to bypass.
    Returns `{imported, domain, browser, cookies}`.

    Extracts cookies for the specified domain from the user's real browser
    (reading its local SQLite database) and injects them into the current
    automation session via CDP.

    On macOS, the system Keychain dialog will prompt the user to authorize
    access — this serves as implicit user consent.

    Args:
        tab: Tab instance (automation browser to inject cookies into)
        domain: Domain to import cookies for (e.g. ".grok.com")
        browser: Source browser. One of: "chrome", "chromium", "brave",
                 "edge". Default: "chrome".

    Returns:
        dict with keys: imported (int), domain, browser, cookies (list
        of name/domain pairs for confirmation).
    """
    cookies = cookies_extract(domain, browser)

    if not cookies:
        return {
            "imported": 0,
            "domain": domain,
            "browser": browser,
            "error": f"No cookies found for {domain} in {browser}",
        }

    # Inject via CDP Storage.setCookies
    from ..cdp import network as cdp_network, storage

    cookie_params = []
    for c in cookies:
        param = cdp_network.CookieParam(
            name=c["name"],
            value=c["value"],
            domain=c["domain"],
            path=c["path"],
            secure=c["secure"],
            http_only=c["httpOnly"],
            expires=cdp_network.TimeSinceEpoch(c["expires"]) if c["expires"] else None,
        )
        cookie_params.append(param)

    conn = tab.browser.connection
    await conn.send(storage.set_cookies(cookie_params), _is_update=True)

    return {
        "imported": len(cookies),
        "domain": domain,
        "browser": browser,
        "cookies": [{"name": c["name"], "domain": c["domain"]} for c in cookies],
    }
