"""Keep real tool selection and failure guidance reachable across the catalog."""

import inspect
from typing import Literal

import pytest

from ai_dev_browser import core
from ai_dev_browser._cli import (
    INJECTED_FIRST_PARAMS,
    _augment_failure,
    _exception_failure,
    _generate_parser,
    _parse_docstring_args,
    _parse_docstring_failure,
    wrap_core,
    wrap_core_sync,
)
from ai_dev_browser.tools._generate import _discover_tools


@pytest.mark.parametrize("tool", _discover_tools(), ids=lambda tool: tool["name"])
def test_catalog_help_preserves_each_parameter_and_recovery(tool):
    function = getattr(core, tool["name"])
    doc = inspect.getdoc(function)
    assert doc and doc.startswith("Use when:"), tool["name"]
    assert _parse_docstring_failure(doc), tool["name"]
    descriptions = _parse_docstring_args(doc)
    parser = _generate_parser(function, requires_tab=tool["requires_tab"])
    help_text = " ".join(parser.format_help().split())
    for name, parameter in inspect.signature(function).parameters.items():
        if name in INJECTED_FIRST_PARAMS:
            continue
        assert name in descriptions, (tool["name"], name)
        # argparse may wrap a long command/path in the middle of a word.
        assert "".join(descriptions[name].split()) in "".join(help_text.split()), (
            tool["name"],
            name,
        )
        action = next(action for action in parser._actions if action.dest == name)
        assert action.default == parameter.default or action.required


def test_optional_choices_and_required_containers_are_validated_before_dispatch():
    def configure(
        items: dict, labels: list[str], mode: Literal["safe", "demo"] | None = None
    ):
        pass

    parser = _generate_parser(configure, requires_tab=False)
    with pytest.raises(SystemExit) as missing:
        parser.parse_args([])
    assert missing.value.code == 2
    with pytest.raises(SystemExit) as invalid:
        parser.parse_args(["--items", "{}", "--labels", "x", "--mode", "unknown"])
    assert invalid.value.code == 2
    parsed = parser.parse_args(["--items", '{"x":1}', "--labels", "one", "two"])
    assert parsed.items == {"x": 1} and parsed.labels == ["one", "two"]
    assert parsed.mode is None


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_error_only_failure_reaches_runtime_recovery(asynchronous):
    def failed():
        """Use when: a fixture forces the original error-only convention.

        Failure:
            Inspect committed state before deciding whether to write again.
        """
        return {"error": "write response lost"}

    if asynchronous:

        async def async_failed():
            return failed()

        async_failed.__doc__ = failed.__doc__
        result = await wrap_core(async_failed)()
    else:
        result = wrap_core_sync(failed)()
    assert result == {
        "error": "write response lost",
        "error_code": "error",
        "retryable": False,
        "hint": "Inspect committed state before deciding whether to write again.",
    }


def test_explicit_diagnosis_and_recovery_win_over_no_target_message():
    class ConsentRefused(RuntimeError):
        error_code = "auth_failed"
        retryable = False
        hint = "Consent was revoked; ask the user before proceeding."
        details = {"state": "revoked"}

    result = _exception_failure(
        ConsentRefused("no target after consent revoked"), "generic"
    )
    assert result["error_code"] == "auth_failed" and result["retryable"] is False
    assert result["hint"] == ConsentRefused.hint
    assert result["details"] == ConsentRefused.details
    assert _augment_failure(dict(result), result["error"]) == result


def test_explicit_exception_hint_survives_even_without_explicit_category():
    error = RuntimeError("no target for Page.navigate")
    error.hint = "Inspect the returned successor identity before selecting a page."
    result = _exception_failure(error, "generic")
    assert result["error_code"] == "no_target"
    assert result["hint"] == error.hint


def test_lifecycle_cli_outer_exception_keeps_structured_recovery(monkeypatch, capsys):
    from ai_dev_browser._cli import as_cli

    class IdentityChanged(RuntimeError):
        error_code = "session_changed"
        retryable = False
        hint = "Inspect the original session; do not replay input."
        details = {"state": "replaced"}

    @as_cli(requires_tab=False)
    def lifecycle():
        raise IdentityChanged("no target after identity changed")

    monkeypatch.setattr("sys.argv", ["lifecycle"])
    with pytest.raises(SystemExit) as stopped:
        lifecycle.cli_main()
    assert stopped.value.code == 5
    import json

    result = json.loads(capsys.readouterr().out)
    assert result["error_code"] == "session_changed"
    assert result["retryable"] is False
    assert result["hint"] == IdentityChanged.hint
    assert result["details"] == IdentityChanged.details
