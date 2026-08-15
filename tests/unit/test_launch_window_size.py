"""launch_chrome sizes the OS window to the desktop viewport in *windowed* mode,
so a headed browser opens desktop-sized instead of Chrome's cramped ~800x600
default (and innerWidth then already matches, so get_active_tab's device-metrics
override is skipped and the page renders 1:1 with no down-scaling). Headless has
no visible window — its viewport comes from the device-metrics override — so it
gets no --window-size.

Captures the launcher argv (Popen + find_chrome monkeypatched) so the test needs
neither a real Chrome nor a display.
"""

from __future__ import annotations

import pytest

from ai_dev_browser.core import chrome
from ai_dev_browser.core.config import (
    DEFAULT_VIEWPORT_HEIGHT,
    DEFAULT_VIEWPORT_WIDTH,
    VIEWPORT_ENV,
)


class _FakePopen:
    pid = 12345
    stderr = None

    def poll(self):
        return None


@pytest.fixture
def launch_args(monkeypatch, tmp_path):
    """Return a callable that runs launch_chrome and hands back the argv it
    would have spawned, without launching anything."""
    calls: dict = {}

    def fake_popen(args, **kwargs):
        calls["args"] = list(args)
        return _FakePopen()

    monkeypatch.setattr(chrome, "find_chrome", lambda: "chrome")
    monkeypatch.setattr(chrome.subprocess, "Popen", fake_popen)

    def run(**kwargs):
        chrome.launch_chrome(user_data_dir=str(tmp_path), **kwargs)
        return calls["args"]

    return run


def _window_size_flags(args) -> list[str]:
    return [a for a in args if a.startswith("--window-size")]


def test_windowed_sizes_window_to_default_viewport(launch_args, monkeypatch):
    monkeypatch.delenv(VIEWPORT_ENV, raising=False)
    args = launch_args(headless=False)
    assert (
        f"--window-size={DEFAULT_VIEWPORT_WIDTH},{DEFAULT_VIEWPORT_HEIGHT}" in args
    ), _window_size_flags(args)


def test_headless_gets_no_window_size(launch_args, monkeypatch):
    """Headless has no visible window; device-metrics is its viewport lever."""
    monkeypatch.delenv(VIEWPORT_ENV, raising=False)
    args = launch_args(headless=True)
    assert not _window_size_flags(args), _window_size_flags(args)


def test_env_overrides_window_size(launch_args, monkeypatch):
    monkeypatch.setenv(VIEWPORT_ENV, "1440x900")
    args = launch_args(headless=False)
    assert "--window-size=1440,900" in args, _window_size_flags(args)


def test_env_native_drops_window_size(launch_args, monkeypatch):
    """Opt-out is consistent: native leaves both the window size and the
    device-metrics viewport untouched."""
    monkeypatch.setenv(VIEWPORT_ENV, "native")
    args = launch_args(headless=False)
    assert not _window_size_flags(args), _window_size_flags(args)
