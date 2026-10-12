"""Rejected operations cannot inherit a stale successful connection state."""

from ai_dev_browser.core._session import failure


def test_failure_preserves_identity_and_legacy_message_but_rejects_operation():
    observed = {
        "session_id": "test-session",
        "port": 9222,
        "message": "Browser started",
        "connected": True,
        "error": "previous error",
        "error_code": "previous_code",
        "retryable": True,
    }
    rejected = failure("unowned", "Restart requires ownership", **observed)
    assert rejected["session_id"] == observed["session_id"]
    assert rejected["port"] == observed["port"]
    assert rejected["message"] == observed["message"]
    assert rejected["connected"] is False
    assert rejected["error"] == "Restart requires ownership"
    assert rejected["error_code"] == "unowned"
    assert rejected["retryable"] is False
