"""Tests for camel_to_snake — covers the acronym-handling bug that broke
every CDP command carrying acronym kwargs (Runtime.evaluate's
allowUnsafeEvalBlockedByCSP, DOM.getHTML, Network.setUserAgentOverride …).

The naive single-pass `re.sub(r"(?<!^)(?=[A-Z])", "_", n).lower()` failed on
acronyms; this test matrix locks the corrected two-pass behavior in.
"""

import pytest

from ai_dev_browser.core._case import camel_to_snake


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Simple lower-Upper boundary
        ("userAgent", "user_agent"),
        ("captureScreenshot", "capture_screenshot"),
        ("getDocument", "get_document"),
        # Trailing acronym (the original bug)
        ("allowUnsafeEvalBlockedByCSP", "allow_unsafe_eval_blocked_by_csp"),
        ("getHTML", "get_html"),
        ("setHTMLContent", "set_html_content"),
        # Embedded acronym
        ("XMLHttpRequest", "xml_http_request"),
        ("getHTMLTitle", "get_html_title"),
        ("simpleHTTPServer", "simple_http_server"),
        # Acronym at start (PascalCase)
        ("URLPath", "url_path"),
        ("HTTPClient", "http_client"),
        # All-caps short identifier
        ("URL", "url"),
        ("CSP", "csp"),
        ("X", "x"),
        # Digits — should not be split inside numbers, but lower→Upper
        # boundary still applies after a digit run.
        ("ipv4Address", "ipv4_address"),
        ("base64Encode", "base64_encode"),
        ("v2API", "v2_api"),
        # Already snake_case — pass through unchanged
        ("user_agent", "user_agent"),
        ("url", "url"),
        # Single lowercase letter
        ("a", "a"),
        # Empty string
        ("", ""),
        # CDP method names (PascalCase first char) — no leading underscore
        ("Browser", "browser"),
        ("DOMSnapshot", "dom_snapshot"),
    ],
)
def test_camel_to_snake(raw, expected):
    assert camel_to_snake(raw) == expected


def test_camel_to_snake_matches_real_cdp_python_param():
    """Sanity check against the actual cdp-python signature that triggered
    the original bug — guards against the fix drifting from cdp-python's
    naming convention."""
    import inspect

    from ai_dev_browser.cdp.runtime import evaluate

    converted = camel_to_snake("allowUnsafeEvalBlockedByCSP")
    assert converted in inspect.signature(evaluate).parameters
