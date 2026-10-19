"""Unit fault/race coverage supplements real Chrome ownership workflows."""

from pathlib import Path
import shutil
import subprocess

from ai_dev_browser._cli import _exception_failure, _exit_code_for_result
from ai_dev_browser.core._transport import OwnershipProtocolError, ProtocolException
from ai_dev_browser.core.errors import SessionError
import pytest


def test_extension_ownership_state_machine():
    node = shutil.which("node")
    assert node, "Node.js is required for extension state/race unit tests"
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [node, "--test", "tests/unit/extension_ownership.test.cjs"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "state,code,exit_code",
    [
        ("closed", "target_closed", 4),
        ("replaced", "session_changed", 5),
        ("revoked", "auth_failed", 7),
        ("unavailable", "unsupported", 6),
        ("unowned", "unsupported", 6),
    ],
)
def test_ownership_failure_preserves_protocol_session_and_cli_contract(
    state, code, exit_code
):
    details = {"state": state, "target_id": "11"}
    error = OwnershipProtocolError(
        {"message": "Ownership refused", "data": {"adbOwnership": details}}
    )
    assert isinstance(error, (ProtocolException, SessionError))
    assert isinstance(error, ProtocolException) and isinstance(error, SessionError)
    envelope = _exception_failure(error, "generic tool hint")
    assert envelope["error_code"] == code and envelope["retryable"] is False
    assert envelope["details"] == details
    assert "Do not replay" in envelope["hint"]
    assert _exit_code_for_result(envelope) == exit_code
