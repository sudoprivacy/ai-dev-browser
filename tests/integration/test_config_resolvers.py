"""Hermetic tests for config env-var resolvers (no browser, runs in CI).

resolve_startup_timeout backs browser_start's `startup_timeout=None` default and
the AI_DEV_BROWSER_STARTUP_TIMEOUT knob CI uses to give slow Windows runners
headroom — so its precedence (explicit arg > env > default) and its rejection of
junk env values are worth pinning.
"""

from __future__ import annotations

import pytest

from ai_dev_browser.core.config import (
    DEFAULT_STARTUP_TIMEOUT,
    STARTUP_TIMEOUT_ENV,
    resolve_startup_timeout,
)


def test_explicit_arg_wins_over_env(monkeypatch):
    monkeypatch.setenv(STARTUP_TIMEOUT_ENV, "90")
    # An explicit value must override the env — including the tight timeout the
    # orphan-cleanup regression test relies on.
    assert resolve_startup_timeout(0.001) == 0.001
    assert resolve_startup_timeout(45.0) == 45.0


def test_env_used_when_no_explicit(monkeypatch):
    monkeypatch.setenv(STARTUP_TIMEOUT_ENV, "90")
    assert resolve_startup_timeout(None) == 90.0


def test_default_when_env_absent(monkeypatch):
    monkeypatch.delenv(STARTUP_TIMEOUT_ENV, raising=False)
    assert resolve_startup_timeout(None) == DEFAULT_STARTUP_TIMEOUT


@pytest.mark.parametrize("junk", ["", "  ", "abc", "0", "-5", "nan"])
def test_unparsable_or_nonpositive_env_falls_back_to_default(monkeypatch, junk):
    # A junk or non-positive env must NOT silently disable the wait (a 0s timeout
    # would kill every cold-starting Chrome instantly).
    monkeypatch.setenv(STARTUP_TIMEOUT_ENV, junk)
    assert resolve_startup_timeout(None) == DEFAULT_STARTUP_TIMEOUT
