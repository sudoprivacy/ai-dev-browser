"""Hermetic tests for browser_start's cold-start-miss retry + port spreading.

No real Chrome — launch_chrome / is_port_in_use / the registry are mocked so we
exercise the control flow deterministically. Guards the CI flake fix: on a
loaded host (esp. Windows) Chrome can fail to bind its debug port even though
the request is fine; a relaunch on a fresh port clears it. Runs in CI.
"""

from __future__ import annotations

import ai_dev_browser.core.browser as b
import ai_dev_browser.core.port as port_mod


class _FakeProc:
    def __init__(self, pid: int):
        self.pid = pid
        self.stderr = None

    def poll(self):
        return None  # never exits on its own


def _stub_success_path(monkeypatch, tmp_path):
    monkeypatch.setattr(b, "_kill_process_tree", lambda pid: None)
    monkeypatch.setattr(b, "_query_chrome_guid", lambda port: "guid")
    monkeypatch.setattr(b, "_query_initial_page", lambda port: "initial-page")
    monkeypatch.setattr(b, "_query_chrome_version", lambda port: None)
    monkeypatch.setattr(b.registry, "register_instance", lambda **kw: None)
    monkeypatch.setattr(b.registry, "lookup", lambda *args: None)
    monkeypatch.setattr(b._session, "_DIR", tmp_path / "sessions")
    monkeypatch.setattr(b._session, "process_info", lambda pid: None)
    creations = []

    async def create(port, guid, url, timeout):
        assert url == "about:blank"
        return "initial-page"

    monkeypatch.setattr(b, "_create_startup_page", create)

    async def wait_page(port, target_id, url, timeout):
        assert target_id == "initial-page"
        creations.append((port, url))

    monkeypatch.setattr(b, "_prepare_startup_page", wait_page)
    return creations


def test_auto_port_retries_on_cold_start_miss(monkeypatch, tmp_path):
    creations = _stub_success_path(monkeypatch, tmp_path)
    ports = iter([9350, 9351])
    monkeypatch.setattr(b, "get_available_port", lambda **kw: next(ports))

    launched: list[int] = []
    procs = iter([_FakeProc(1001), _FakeProc(1002)])

    def fake_launch(**kw):
        assert kw["start_url"] == ""
        launched.append(kw["port"])
        return next(procs)

    monkeypatch.setattr(b, "launch_chrome", fake_launch)
    # First port never binds; the retry port does.
    monkeypatch.setattr(b, "is_port_in_use", lambda port=None, **kw: port == 9351)

    result = b.browser_start(
        temp=True, headless=True, startup_timeout=0.05, url="https://neutral.test/once"
    )

    assert "error" not in result, result
    assert result["port"] == 9351, "should have retried on the fresh port"
    assert launched == [9350, 9351], "should relaunch exactly once, on a new port"
    assert creations == [(9351, "https://neutral.test/once")]


def test_pinned_port_does_not_retry(monkeypatch, tmp_path):
    _stub_success_path(monkeypatch, tmp_path)
    monkeypatch.setattr(b, "get_available_port", lambda **kw: 9999)  # must not be used

    launched: list[int] = []

    def fake_launch(**kw):
        launched.append(kw["port"])
        return _FakeProc(2001)

    monkeypatch.setattr(b, "launch_chrome", fake_launch)
    # Pre-check sees the pinned port free; then it never binds → time out, no retry.
    monkeypatch.setattr(b, "is_port_in_use", lambda port=None, **kw: False)

    result = b.browser_start(port=9412, temp=True, headless=True, startup_timeout=0.05)

    assert "error" in result, "a pinned port that never binds must fail (not retry)"
    assert launched == [9412], "a caller-pinned port must not be relaunched elsewhere"


def test_randomize_spreads_ports(monkeypatch):
    # With randomize, consecutive fresh allocations must not all return the low
    # port — that deterministic reuse is what turned a transient Windows re-bind
    # rejection into a repeatable flake. Every port is 'bindable' here.
    monkeypatch.setattr(port_mod, "_is_port_bindable", lambda host, p: True)
    seen = {port_mod.get_available_port(reuse=False, randomize=True) for _ in range(30)}
    assert len(seen) > 1, f"randomize should spread across the band, got {seen}"
