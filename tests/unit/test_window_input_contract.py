"""Session refusals must survive input fallbacks and window error reporting."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_dev_browser.core.ax import _fill_verified
from ai_dev_browser.core.errors import InputUnavailableError, SessionError
from ai_dev_browser.core.extension import (
    extension_version_info,
    query_extension_version,
)
from ai_dev_browser.core.mouse import mouse_click
from ai_dev_browser.core.window import window_set
from ai_dev_browser.core._session import describe


@pytest.mark.parametrize("prefer", [None, "keys", "human"])
@pytest.mark.parametrize(
    "error", [InputUnavailableError("hidden"), SessionError("revoked", "auth_failed")]
)
async def test_refused_typing_never_clears_focuses_or_uses_a_fallback(prefer, error):
    tab = SimpleNamespace(_prepare_input=AsyncMock(side_effect=error), send=AsyncMock())
    element = SimpleNamespace(apply=AsyncMock(), focus=AsyncMock())
    with pytest.raises(SessionError) as caught:
        await _fill_verified(tab, element, "keep private", prefer=prefer)
    assert caught.value is error
    element.apply.assert_not_called()
    element.focus.assert_not_called()
    tab.send.assert_not_called()


async def test_dispatch_refusal_does_not_advance_to_native_value_setter():
    error = InputUnavailableError("became hidden")
    tab = SimpleNamespace(_prepare_input=AsyncMock(), send=AsyncMock(side_effect=error))
    element = SimpleNamespace(apply=AsyncMock(), focus=AsyncMock())
    with pytest.raises(InputUnavailableError) as caught:
        await _fill_verified(tab, element, "keep private", prefer="keys")
    assert caught.value is error
    assert all(
        "getOwnPropertyDescriptor" not in call.args[0]
        for call in element.apply.await_args_list
    )
    tab.send.assert_awaited_once()


async def test_refused_positioning_move_never_advances_to_click():
    error = InputUnavailableError("hidden")
    tab = SimpleNamespace(
        mouse_move=AsyncMock(side_effect=error), mouse_click=AsyncMock()
    )
    with pytest.raises(InputUnavailableError) as caught:
        await mouse_click(tab, 10, 20, human_like=False)
    assert caught.value is error
    tab.mouse_click.assert_not_called()


@pytest.mark.parametrize(
    "options", [{"state": "typo"}, {"state": "minimized", "focus": True}]
)
async def test_invalid_window_requests_fail_before_touching_the_page(options):
    with pytest.raises(ValueError):
        await window_set(object(), **options)


def test_unknown_loaded_version_remains_unknown_in_session_results():
    info = extension_version_info(None)
    assert (
        info["extension_version"] is None
        and info["extension_version_matches_bundle"] is None
    )
    assert info["bundled_extension_version"]
    result = describe({"transport": "extension", **info})
    assert all(result[key] == value for key, value in info.items())
    assert (
        extension_version_info(info["bundled_extension_version"])[
            "extension_version_matches_bundle"
        ]
        is True
    )
    assert extension_version_info("0.0.0")["extension_version_matches_bundle"] is False


async def test_live_version_report_wins_over_an_older_bridge_hello():
    connection = SimpleNamespace(
        send=AsyncMock(return_value={"extensionVersion": "observed"})
    )
    assert (
        await query_extension_version(SimpleNamespace(connection=connection), "stale")
        == "observed"
    )
    connection.send.side_effect = RuntimeError("older extension lacks diagnostics")
    assert await query_extension_version(SimpleNamespace(connection=connection)) is None


def test_input_refusal_preserves_a_useful_cli_envelope():
    from ai_dev_browser._cli import _exception_failure

    details = {"input_sent": False, "visibility": "hidden", "focused": True}
    failure = _exception_failure(
        InputUnavailableError("original reason", details=details),
        "generic click advice",
    )
    assert (
        failure["error"] == "original reason" and failure["error_code"] == "unsupported"
    )
    assert failure["details"] == details and failure["retryable"] is False
    assert "chrome://extensions" in failure["hint"]


def test_bridge_records_insert_text_command_without_its_value(caplog):
    from ai_dev_browser.core.ext_bridge import _Bridge

    caplog.set_level("INFO", logger="ai_dev_browser.core.ext_bridge")
    _Bridge()._log_action("Input.insertText", {"text": "private fixture value"})
    assert [record.getMessage() for record in caplog.records] == [
        "action: Input.insertText"
    ]
