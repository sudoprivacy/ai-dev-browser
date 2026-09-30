"""Unknown bindings use wire JSON; errors in known bindings remain errors."""

import pytest

from ai_dev_browser.core.cdp import _get_cdp_command, cdp_send


@pytest.mark.parametrize("method", ["AiDevBrowser.debugState", "Page.futureCommand"])
def test_unbound_command_preserves_wire_keys_and_result(method):
    params = {"targetId": "7", "nestedValue": {"someKey": [1, 2]}}
    command = _get_cdp_command(method, params)
    assert next(command) == {"method": method, "params": params}
    result = {"autoTabs": [7]}
    with pytest.raises(StopIteration) as stopped:
        command.send(result)
    assert stopped.value.value is result


def test_known_binding_error_does_not_fall_back_to_raw():
    with pytest.raises(TypeError):
        _get_cdp_command("Runtime.evaluate", {"nonexistentParam": True})


@pytest.mark.parametrize("method", ["", "Runtime", "Runtime.", "A.B.C"])
def test_invalid_method_is_validation_error(method):
    with pytest.raises(ValueError, match="Invalid CDP method"):
        _get_cdp_command(method, {})


@pytest.mark.parametrize("params", ["[]", "null", "true", '"text"'])
async def test_params_must_be_an_object(params):
    with pytest.raises(ValueError, match="Invalid CDP params"):
        await cdp_send(None, "Runtime.evaluate", params)
