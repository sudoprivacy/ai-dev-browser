# Derived from Mosswork moss-browser. Copyright (c) 2026 OrcaKit.
# Original MIT terms are retained in MIT-LICENSE.txt.
"""Privacy and redaction helpers for record/replay."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ai_dev_browser.record.models import PrivacySettings

SENSITIVE_RE = re.compile(r"password|token|secret|key|code|otp|auth|session|jwt", re.I)
URL_KEYS = {
    "token",
    "access_token",
    "refresh_token",
    "code",
    "state",
    "session",
    "key",
    "secret",
    "password",
    "auth",
    "jwt",
    "id_token",
    "auth_token",
    "client_secret",
    "authorization",
}


def redact_url(raw: str, privacy: PrivacySettings | None = None) -> str:
    policy = (privacy or PrivacySettings()).url_query_policy
    if policy == "none":
        return raw
    try:
        parts = urlsplit(raw)
        # Parsing the port also rejects malformed URLs before an unredacted
        # value can become a durable step/draft. Basic-auth userinfo is never
        # retained by either masking policy.
        parts.port
        netloc = parts.netloc.rsplit("@", 1)[-1]

        def mask_pairs(value: str) -> str:
            return urlencode(
                [
                    (
                        key,
                        "***"
                        if policy == "mask-all" or key.lower() in URL_KEYS
                        else item,
                    )
                    for key, item in parse_qsl(value, keep_blank_values=True)
                ]
            )

        fragment = parts.fragment
        if "?" in fragment:
            path, values = fragment.split("?", 1)
            fragment = path + "?" + mask_pairs(values)
        elif "=" in fragment:
            fragment = mask_pairs(fragment)
        elif fragment and policy == "mask-all":
            fragment = "***"
        return urlunsplit(
            (parts.scheme, netloc, parts.path, mask_pairs(parts.query), fragment)
        )
    except (TypeError, ValueError):
        raise ValueError("Invalid recorded URL") from None


def is_sensitive_target(target: dict[str, Any] | None) -> bool:
    if not target:
        return False
    haystack = " ".join(
        str(target.get(k, ""))
        for k in (
            "type",
            "name",
            "accessibleName",
            "nameAttr",
            "placeholder",
            "ariaLabel",
            "id",
        )
    )
    return bool(SENSITIVE_RE.search(haystack))


def redact_event(
    event: dict[str, Any], privacy: PrivacySettings | None = None
) -> dict[str, Any]:
    p = privacy or PrivacySettings()
    copied = dict(event)
    page = copied.get("page")
    if isinstance(page, dict) and isinstance(page.get("url"), str):
        page = dict(page)
        page["url"] = redact_url(page["url"], p)
        copied["page"] = page
    for key in ("url", "urlBefore", "urlAfter"):
        if isinstance(copied.get(key), str):
            copied[key] = redact_url(copied[key], p)
    if "value" in copied:
        if p.input_policy == "mask-all" or (
            p.input_policy == "mask-sensitive"
            and is_sensitive_target(copied.get("target"))
        ):
            copied["value"] = "{{sensitive_value}}"
            copied["redacted"] = True
    return copied
