"""Owned CDP download settings keep the SDK's actual transport and fences."""

from types import SimpleNamespace

import pytest

from ai_dev_browser.remote.control import ControlError
from ai_dev_browser.remote.session import BrowserSession


def make_session(transport):
    calls = []

    class Files:
        def download_directory(self):
            return "owned/downloads"

    class Browser:
        async def call(self, method, params):
            calls.append((method, params))
            return {}

    session = BrowserSession(
        SimpleNamespace(_automation_target_id="owned", transport=transport),
        None,
        files=Files(),
    )

    async def connect():
        return Browser()

    session._connect_browser = connect
    return session, calls


async def current():
    return None


@pytest.mark.parametrize("transport", [None, "cdp"])
async def test_actual_cdp_transport_configures_only_owned_download_directory(transport):
    session, calls = make_session(transport)
    await session._configure_downloads("ai", 0, 0, before_effect=current)
    assert calls == [
        (
            "Browser.setDownloadBehavior",
            {"behavior": "allow", "downloadPath": "owned/downloads"},
        )
    ]


async def test_personal_extension_transport_retains_existing_download_preferences():
    session, calls = make_session("extension")
    await session._configure_downloads("ai", 0, 0, before_effect=current)
    assert calls == []


async def test_download_setting_is_not_sent_after_host_withdrawal():
    session, calls = make_session("cdp")

    async def denied():
        raise PermissionError("original private grant")

    with pytest.raises(ControlError, match="browser_authorization_denied"):
        await session._configure_downloads("ai", 0, 0, before_effect=denied)
    assert calls == []


async def test_target_withdrawal_during_directory_check_prevents_configuration():
    session, calls = make_session(None)

    def changed():
        session.control.change_target()
        return "owned/downloads"

    session.files.download_directory = changed
    with pytest.raises(ControlError, match="stale_browser_operation"):
        await session._configure_downloads("ai", 0, 0, before_effect=current)
    assert calls == []


async def test_human_takeover_during_connection_prevents_configuration():
    session, calls = make_session(None)
    connect = session._connect_browser

    async def taken():
        browser = await connect()
        await session.control.take("human")
        return browser

    session._connect_browser = taken
    with pytest.raises(ControlError, match="stale_browser_operation|held_by_user"):
        await session._configure_downloads("ai", 0, 0, before_effect=current)
    assert calls == []
