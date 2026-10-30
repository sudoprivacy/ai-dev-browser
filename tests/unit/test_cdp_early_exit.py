"""Retain an actual launch exit reason without inventing permission failures."""

from types import SimpleNamespace

import pytest

from ai_dev_browser.core import browser


@pytest.mark.parametrize("exit_code", [-9, -5, 0])
def test_early_exit_preserves_process_and_code_without_retry(
    monkeypatch, tmp_path, exit_code
):
    import tempfile

    launches = []

    def launch(**options):
        launches.append(options)
        return SimpleNamespace(pid=12345, stderr=None, poll=lambda: exit_code)

    monkeypatch.setattr(tempfile, "mkdtemp", lambda **_options: str(tmp_path))
    monkeypatch.setattr(browser, "launch_chrome", launch)
    monkeypatch.setattr(browser, "is_port_in_use", lambda **_options: False)
    result = browser.browser_start(port=31977, headless=True, temp=True)
    assert result["exit_code"] == exit_code
    assert result["pid"] == 12345
    assert str(exit_code) in result["error"]
    assert "Insufficient permissions" not in result["error"]
    assert len(launches) == 1
