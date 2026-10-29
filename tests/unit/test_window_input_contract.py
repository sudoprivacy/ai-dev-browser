"""Session refusals must survive input fallbacks and window error reporting."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_dev_browser.core._session import describe
from ai_dev_browser.core.ax import _fill_verified, click_by_ref
from ai_dev_browser.core.errors import InputUnavailableError, SessionError
from ai_dev_browser.core.extension import (
    bridge_version_info,
    extension_version_info,
    query_extension_state,
    query_extension_version,
)
from ai_dev_browser.core.mouse import mouse_click
from ai_dev_browser.core.window import window_set


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
    element = SimpleNamespace(
        apply=AsyncMock(return_value={"kind": "plain"}), focus=AsyncMock()
    )
    with pytest.raises(InputUnavailableError) as caught:
        await _fill_verified(tab, element, "keep private", prefer="keys")
    assert caught.value is error
    assert all(
        "getOwnPropertyDescriptor" not in call.args[0]
        for call in element.apply.await_args_list
    )
    tab.send.assert_awaited_once()


async def test_click_resolution_refusal_stops_before_any_fallback_query():
    error = SessionError("revoked while resolving the target", "auth_failed")
    tab = SimpleNamespace(
        _prepare_input=AsyncMock(),
        evaluate=AsyncMock(return_value={"url": "https://fixture.invalid/"}),
        send=AsyncMock(side_effect=error),
    )
    with pytest.raises(SessionError) as caught:
        await click_by_ref(tab, "1#2")
    assert caught.value is error
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
    assert "unknown" in info["extension_warning"]
    assert "Before page input" in info["extension_warning"]
    assert "chrome://extensions" in info["extension_warning"]
    result = describe({"transport": "extension", **info})
    assert all(result[key] == value for key, value in info.items())
    assert (
        extension_version_info(info["bundled_extension_version"])[
            "extension_version_matches_bundle"
        ]
        is True
    )
    assert extension_version_info("0.0.0")["extension_version_matches_bundle"] is False
    assert "differs" in extension_version_info("0.0.0")["extension_warning"]
    assert (
        extension_version_info(info["bundled_extension_version"])["extension_warning"]
        is None
    )


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


@pytest.mark.parametrize("version", [None, "0.0.0"])
def test_bridge_runtime_is_not_inferred_from_client_or_extension(version):
    result = bridge_version_info({"bridge_runtime_version": version})
    assert result["bridge_runtime_version"] == version
    assert result["bridge_version_matches_client"] is (False if version else None)
    assert result["bridge_driver_connections"] is None
    assert "does not restart" in result["bridge_warning"]
    assert "Disconnect releases other controllers" in result["bridge_warning"]


async def test_observation_refuses_to_replace_revocation_with_visibility_advice():
    from ai_dev_browser.core._transport import OwnershipProtocolError

    error = OwnershipProtocolError(
        {"message": "revoked", "data": {"adbOwnership": {"state": "revoked"}}}
    )
    sender = SimpleNamespace(send=AsyncMock(side_effect=error))
    with pytest.raises(OwnershipProtocolError) as caught:
        await query_extension_state(sender)
    assert caught.value is error


async def test_window_focus_success_uses_chrome_window_focus_separately():
    state = {"visibility": "visible", "focused": True}
    tab = SimpleNamespace(
        bring_to_front=AsyncMock(),
        _wait_input_visibility=AsyncMock(return_value=state),
        _input_observation=AsyncMock(
            return_value={
                **state,
                "window_state": "normal",
                "tab_active": True,
                "window_focused": False,
            }
        ),
    )
    result = await window_set(tab, focus=True)
    assert result["focused"] is True and result["window_focused"] is False
    assert result["input_ready"] is True and result["success"] is False
    assert result["retryable"] is False


async def test_older_extension_keeps_focus_unknown_and_preserves_revocation():
    from ai_dev_browser.core._tab import Tab
    from ai_dev_browser.core._transport import OwnershipProtocolError

    bounds = SimpleNamespace(window_state=SimpleNamespace(value="normal"))
    tab = SimpleNamespace(
        _target=SimpleNamespace(target_id="11"),
        _browser=SimpleNamespace(transport="extension"),
        send=AsyncMock(side_effect=[{"extensionVersion": "0.4.8"}, (101, bounds)]),
    )
    result = await Tab._input_observation(
        tab, {"visibility": "hidden", "focused": True}
    )
    assert result["tab_active"] is None and result["window_focused"] is None
    assert result["window_id"] == 101 and result["window_state"] == "normal"
    error = OwnershipProtocolError(
        {"message": "revoked", "data": {"adbOwnership": {"state": "revoked"}}}
    )
    tab.send.side_effect = [{"extensionVersion": "0.4.8"}, error]
    with pytest.raises(OwnershipProtocolError) as caught:
        await Tab._input_observation(tab, {"visibility": "hidden", "focused": True})
    assert caught.value is error
