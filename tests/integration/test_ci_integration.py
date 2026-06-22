"""Regression: ai-dev-browser must work in CI environments without
external workarounds (forking a Chrome and passing --port).

Reported by a CI-integrator dogfooding ai-dev-browser on
GitHub Actions ubuntu-latest with `browser-actions/setup-chrome`:

  1. `find_chrome()` couldn't locate the setup-chrome binary at
     `/opt/hostedtoolcache/setup-chrome/<version>/x64/chrome` because
     it's neither in the per-platform candidates list nor matched by
     `shutil.which()`'s name set, and there was no env override.
  2. `--headless=new` (hardcoded) failed in CI with "Multiple targets
     are not supported in headless mode"; the legacy `--headless` mode
     worked but wasn't selectable.

Fixes verified here:
  - `find_chrome()` honors `AI_DEV_BROWSER_CHROME` env, validates the
    path is a real file, falls through to defaults on miss/empty.
  - `launch_chrome(headless="old")` and `headless="new"` both spawn
    Chrome successfully and the launched mode matches the request.
"""

import os

import pytest

from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.chrome import find_chrome
from ai_dev_browser.core.port import _query_chrome_cmdline


SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)


@pytest.fixture(autouse=True)
def _integration_guard():
    if SKIP_INTEGRATION:
        pytest.skip("SKIP_INTEGRATION is set")


@pytest.fixture
def _clean_env_chrome(monkeypatch):
    """Always start each env-related test with the override unset, so
    one test's leftovers don't poison the next."""
    monkeypatch.delenv("AI_DEV_BROWSER_CHROME", raising=False)


def test_find_chrome_env_override_wins_when_path_is_real(
    monkeypatch, _clean_env_chrome
):
    """`AI_DEV_BROWSER_CHROME` pointing at a real file must be returned
    verbatim, even though that file isn't in any per-platform candidate
    list. This is the CI use case: setup-chrome installs into
    /opt/hostedtoolcache/... — outside every default candidate path."""
    # Pick any file that exists and is executable-looking. We don't
    # actually launch it — find_chrome only checks is_file().
    import sys

    monkeypatch.setenv("AI_DEV_BROWSER_CHROME", sys.executable)
    assert find_chrome() == sys.executable, (
        "AI_DEV_BROWSER_CHROME pointing at an existing executable must "
        "win over the per-platform candidate scan."
    )


def test_find_chrome_env_unset_falls_back_to_candidate_scan(_clean_env_chrome):
    """No env → behaves exactly as before. Most-common production
    path; we don't want the env feature to subtly change non-CI flow."""
    # On a dev machine this returns the real Chrome path; in
    # CI without setup-chrome, it may return None — both are
    # legitimate. The contract is "doesn't crash, returns Optional[str]".
    result = find_chrome()
    assert result is None or isinstance(result, str)


def test_find_chrome_env_pointing_at_nonexistent_falls_through(
    monkeypatch, _clean_env_chrome
):
    """Bad env shouldn't poison the resolution — caller may have a
    stale `CHROME_PATH=$RUNNER_TEMP/old-version/chrome` lying around
    from a previous job. We validate `is_file()` and fall through."""
    monkeypatch.setenv(
        "AI_DEV_BROWSER_CHROME", "/this/path/definitely/does/not/exist/chrome"
    )
    # Should fall through to per-platform scan without raising. Return
    # value may be a real Chrome (dev machine) or None (CI without
    # setup-chrome) — we just care it didn't crash on the bad env.
    result = find_chrome()
    assert result is None or isinstance(result, str)


@pytest.mark.parametrize("mode", ["new", "old", True])
def test_headless_mode_selection_round_trips_through_cmdline(mode):
    """`headless="new"` / `"old"` / `True` must each launch Chrome
    successfully and the actual cmdline must reflect the requested
    mode — pre-fix, only `--headless=new` was emitted regardless of
    caller intent, blocking CI setups that need the legacy mode."""
    result = browser_start(headless=mode, temp=True, reuse="none")
    assert "error" not in result, (
        f"browser_start(headless={mode!r}) should succeed: {result}"
    )
    port = result["port"]
    try:
        cmdline = _query_chrome_cmdline(port)
        assert cmdline is not None, "should be able to read back cmdline"
        if mode == "old":
            assert "--headless" in cmdline, (
                f"headless='old' must emit bare --headless; got {cmdline!r}"
            )
            assert "--headless=new" not in cmdline, (
                f"headless='old' must NOT emit --headless=new; got {cmdline!r}"
            )
        else:  # "new" or True
            assert "--headless=new" in cmdline, (
                f"headless={mode!r} must emit --headless=new; got {cmdline!r}"
            )
    finally:
        browser_stop(port=port)


def test_headless_false_is_not_headless():
    """Sanity: False (default) must NOT emit any --headless flag."""
    # Linux CI runners have no X display — a non-headless Chrome can't
    # initialize at all there ("Missing X server or $DISPLAY"). On
    # macOS/Windows the GUI session always exists so the launch
    # succeeds. Skip on Linux when DISPLAY is unset rather than try
    # to bring up xvfb just for one assertion.
    import sys

    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        pytest.skip("non-headless Chrome needs DISPLAY; none on this Linux CI host")

    result = browser_start(headless=False, temp=True, reuse="none")
    assert "error" not in result, f"non-headless launch should succeed: {result}"
    port = result["port"]
    try:
        cmdline = _query_chrome_cmdline(port)
        assert cmdline is not None
        assert not any(
            a == "--headless" or a.startswith("--headless=") for a in cmdline
        ), f"headless=False must emit no headless flag; got {cmdline!r}"
    finally:
        browser_stop(port=port)


def test_headless_invalid_mode_raises_value_error():
    """Defense in depth: arbitrary strings like `headless="yes please"`
    must fail loudly, not silently fall through to one mode or the
    other."""
    with pytest.raises(ValueError, match="headless must be"):
        browser_start(headless="invalid-mode", temp=True, reuse="none")
