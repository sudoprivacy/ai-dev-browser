"""Host cookie handoffs cannot widen scope or publish credentials in a URL."""

import time

import pytest

from ai_dev_browser.remote.authorized_page import navigation_cookie
from ai_dev_browser.remote.control import ControlError

URL = "http://127.0.0.1:8765/review/session/"


def handoff(url=URL):
    return {
        "name": "review_session",
        "value": "a" * 64,
        "url": url,
        "path": "/review/session/",
        "httpOnly": True,
        "sameSite": "Strict",
        "expires": time.time() + 1800,
    }


@pytest.mark.parametrize(
    "url,secure",
    [
        (URL, False),
        (URL.replace("127.0.0.1", "localhost"), False),
        ("https://review.example/review/session/", True),
    ],
)
def test_host_only_cookie_scope_is_preserved(url, secure):
    cookie = handoff(url)
    assert navigation_cookie(url, cookie) == {**cookie, "secure": secure}
    assert "secure" not in cookie


@pytest.mark.parametrize(
    "url",
    [
        "http://remote.example/review/session/",
        "file:///review/session/",
        "https://user:password@review.example/review/session/",  # pragma: allowlist secret - invalid synthetic input
        URL + "?token=hidden",
        URL + "#hidden",
        URL + "?",
        URL + "#",
        "https://[invalid/",
        "https:///review/session/",
        "https://review.example:invalid/review/session/",
    ],
)
def test_credentials_and_untrusted_transport_are_refused(url):
    with pytest.raises(ControlError, match="invalid_browser_authorized_page"):
        navigation_cookie(url, handoff(url))


@pytest.mark.parametrize(
    "change",
    [
        {"domain": "127.0.0.1"},
        {"url": "https://other.example/review/session/"},
        {"path": "/"},
        {"path": "/review/other/"},
        {"path": "/review/../"},
        {"path": "/review//"},
        {"httpOnly": False},
        {"httpOnly": 1},
        {"sameSite": "None"},
        {"expires": float("inf")},
        {"expires": float("nan")},
        {"expires": True},
        {"expires": 0},
        {"expires": time.time() + 7200},
        {"value": "short"},
        {"value": "a" * 64 + "; other=value"},
        {"name": "bad;name"},
    ],
)
def test_cookie_handoff_cannot_widen_permissions_or_lifetime(change):
    with pytest.raises(ControlError, match="invalid_browser_authorized_page"):
        navigation_cookie(URL, {**handoff(), **change})


def test_a_cookie_cannot_be_exposed_through_the_navigation_url():
    cookie = handoff()
    url = URL + cookie["value"]
    with pytest.raises(ControlError) as caught:
        navigation_cookie(url, {**cookie, "url": url})
    assert cookie["value"] not in str(caught.value)
