"""Validate a narrow host-only session-cookie handoff before browser navigation."""

import ipaddress
import re
import time
from urllib.parse import urlsplit

from .control import ControlError


def navigation_cookie(url, cookie):
    """Return host-only CDP parameters, never an HTTP/agent response payload."""
    error = ControlError("invalid_browser_authorized_page")
    if not isinstance(url, str) or not 1 <= len(url) <= 4096:
        raise error
    try:
        parsed = urlsplit(url)
        if parsed.port == 0:
            raise ValueError("invalid port")
        if parsed.hostname is None:
            raise ValueError("missing host")
        try:
            loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = parsed.hostname == "localhost"
    except ValueError:
        raise error from None
    if (
        parsed.scheme not in {"http", "https"}
        or (parsed.scheme == "http" and not loopback)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "?" in url
        or "#" in url
    ):
        raise error
    if not isinstance(cookie, dict) or set(cookie) != {
        "name",
        "value",
        "url",
        "path",
        "httpOnly",
        "sameSite",
        "expires",
    }:
        raise error
    if (
        not isinstance(cookie["name"], str)
        or not re.fullmatch(r"[A-Za-z0-9_]{1,128}", cookie["name"])
        or not isinstance(cookie["value"], str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{32,1024}", cookie["value"])
        or cookie["value"] in url
        or cookie["url"] != url
        or not isinstance(cookie["path"], str)
        or not re.fullmatch(r"/[A-Za-z0-9_/-]{1,1024}/", cookie["path"])
        or "//" in cookie["path"]
        or not parsed.path.startswith(cookie["path"])
        or cookie["httpOnly"] is not True
        or cookie["sameSite"] != "Strict"
        or type(cookie["expires"]) not in {int, float}
        or not time.time() < cookie["expires"] <= time.time() + 3600
    ):
        raise error
    return {**cookie, "secure": parsed.scheme == "https"}
