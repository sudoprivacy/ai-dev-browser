"""Hermetic tests for the Chrome inventory + scoped cleanup (mocked psutil).

psutil is an optional extra (absent in CI), so a fake psutil is injected to
exercise classification + cleanup scoping deterministically. The safety
invariant under test: `external` (the user's real Chrome) is NEVER an eligible
cleanup target, and the cleanup scope is mandatory.
"""

from __future__ import annotations

import pytest

import ai_dev_browser.core.cleanup as cl
from ai_dev_browser.core.config import (
    DEFAULT_PROFILE_DIR,
    get_workspace_profile_dir,
)


class _FakeProc:
    def __init__(self, pid, name, cmdline):
        self.info = {"pid": pid, "name": name, "cmdline": cmdline}


class _FakePsutil:
    class NoSuchProcess(Exception):
        pass

    class AccessDenied(Exception):
        pass

    def __init__(self, procs):
        self._procs = procs

    def process_iter(self, attrs=None):
        return iter(self._procs)


def _cmd(udd=None, port=None, profile=None, type_=None):
    c = ["chrome.exe"]
    if udd is not None:
        c.append(f"--user-data-dir={udd}")
    if port is not None:
        c.append(f"--remote-debugging-port={port}")
    if profile is not None:
        c.append(f"--profile-directory={profile}")
    if type_ is not None:
        c.append(f"--type={type_}")
    return c


@pytest.fixture
def fake_env(monkeypatch):
    """Wire a fake process table + debug-owner map into the cleanup module."""
    temp_live = "/tmp/ai_dev_browser_9500_live"  # managed temp, has live debug
    temp_orphan = "/tmp/ai_dev_browser_9600_orph"  # managed temp, NO live debug
    ws_orphan = str(get_workspace_profile_dir("myprof"))  # managed workspace, orphan
    external = "C:/Users/me/AppData/Local/Google/Chrome/User Data"  # NOT managed

    procs = [
        _FakeProc(101, "chrome.exe", _cmd(temp_live, 9500, "Default")),
        _FakeProc(202, "chrome.exe", _cmd(temp_orphan, 9600, "Default")),
        _FakeProc(303, "chrome.exe", _cmd(ws_orphan, 9700, "Default")),
        _FakeProc(404, "chrome.exe", _cmd(external, None, "Profile 1")),
        _FakeProc(999, "chrome.exe", _cmd(temp_live, None, type_="renderer")),  # child
    ]
    monkeypatch.setattr(cl, "_require_psutil", lambda: _FakePsutil(procs))
    # Only 9500 has a live debug owner → 9600 / 9700 are orphans.
    monkeypatch.setattr(cl, "find_debug_chromes", lambda: [(9500, 101, None)])
    monkeypatch.setattr(
        cl,
        "_query_chrome_user_data_dir",
        lambda port, **kw: temp_live if port == 9500 else None,
    )
    monkeypatch.setattr(cl, "_kill_process_tree", lambda pid: True)
    return {
        "temp_live": temp_live,
        "temp_orphan": temp_orphan,
        "ws_orphan": ws_orphan,
        "external": external,
    }


def test_list_chromes_classifies_origins_and_skips_renderers(fake_env):
    chromes = cl.list_chromes(all_workspaces=True)
    by_pid = {c["pid"]: c for c in chromes}
    assert 999 not in by_pid, "renderer child (--type=) must be skipped"
    assert by_pid[101]["origin"] == "adb"  # managed + live debug
    assert by_pid[202]["origin"] == "adb-orphan"  # managed temp, no live debug
    assert by_pid[303]["origin"] == "adb-orphan"  # managed workspace, no live debug
    assert by_pid[404]["origin"] == "external"  # user's real Chrome
    assert by_pid[404]["profile"] == "Profile 1"
    assert by_pid[101]["port"] == 9500 and by_pid[404]["port"] is None


def test_cleanup_temp_reaps_only_temp_orphan_never_live_never_external(fake_env):
    res = cl.browser_cleanup(scope="temp", dry_run=True)
    pids = {k["pid"] for k in res["would_kill"]}
    assert pids == {202}, f"only the temp ORPHAN, got {pids}"
    assert 101 not in pids, "must not touch a LIVE adb Chrome"
    assert 404 not in pids, "must NEVER touch the user's external Chrome"


def test_cleanup_workspace_scope_reaps_workspace_orphan(fake_env):
    res = cl.browser_cleanup(scope="workspace", dry_run=True)
    pids = {k["pid"] for k in res["would_kill"]}
    assert 303 in pids, "workspace-profile orphan should be in scope"
    assert 202 not in pids, "a temp orphan is not in the workspace scope"
    assert 404 not in pids


def test_cleanup_profile_scope_requires_profile_name(fake_env):
    with pytest.raises(ValueError, match="requires a profile name"):
        cl.browser_cleanup(scope="profile", dry_run=True)


def test_cleanup_bad_scope_rejected(fake_env):
    with pytest.raises(ValueError, match="scope must be one of"):
        cl.browser_cleanup(scope="everything", dry_run=True)  # type: ignore[arg-type]


def test_external_is_never_managed():
    # The structural guarantee: a path outside adb's namespace is never managed,
    # so it can never be a cleanup target regardless of scope.
    assert not cl._is_managed_profile(
        cl._normalize_path("C:/Users/me/AppData/Local/Google/Chrome/User Data")
    )
    assert cl._is_managed_profile(cl._normalize_path("/tmp/ai_dev_browser_1_x"))
    assert cl._is_managed_profile(
        cl._normalize_path(str(DEFAULT_PROFILE_DIR / "slug" / "prof"))
    )
