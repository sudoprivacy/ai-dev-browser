"""Stale-state errors must tell the model how to recover; other codes pass through."""

from ai_dev_browser.remote.worker import mcp_error_text


def test_stale_errors_carry_recovery_hints():
    stale = mcp_error_text("stale_browser_operation")
    assert stale.startswith("stale_browser_operation")
    assert "browser_observe" in stale and "epochs" in stale
    restart = mcp_error_text("browser_restart_requires_observation")
    assert restart.startswith("browser_restart_requires_observation")
    assert "browser_observe" in restart and "browser_launch" in restart


def test_other_codes_pass_through_unchanged():
    assert mcp_error_text("browser_profile_in_use") == "browser_profile_in_use"
    assert mcp_error_text("browser_not_started") == "browser_not_started"
