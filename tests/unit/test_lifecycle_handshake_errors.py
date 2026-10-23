"""Guard the cold-start error observed on the actual Ubuntu release gate."""

from ai_dev_browser.core import _session, browser
import pytest


def test_missing_identity_preserves_launch_message_without_overriding_failure(
    monkeypatch,
):
    monkeypatch.setattr(browser, "_query_chrome_guid", lambda port: None)
    result = browser._describe_cdp(
        {"port": 9355, "pid": 1234, "message": "Browser started", "connected": True}
    )
    assert result["error_code"] == "transient" and result["retryable"]
    assert result["connected"] is False and result["browser_closed"] is False
    assert result["pid"] == 1234 and result["message"] == "Browser started"


@pytest.mark.parametrize("ambiguous_reply", [False, True])
def test_launch_creates_one_page_after_identity_without_replay(
    monkeypatch, ambiguous_reply
):
    class Process:
        pid = 1234
        stderr = None

        def poll(self):
            return None

    launches = []

    def launch(**options):
        launches.append(options)
        return Process()

    queries = []

    def guid(port):
        queries.append(port)
        return "ready" if len(queries) >= 2 else None

    monkeypatch.setattr(browser, "launch_chrome", launch)
    monkeypatch.setattr(browser, "get_available_port", lambda **kw: 9355)
    monkeypatch.setattr(browser, "is_port_in_use", lambda **kw: True)
    monkeypatch.setattr(browser, "_query_chrome_guid", guid)
    creations = []

    async def create(port, guid, url, timeout):
        creations.append((port, guid, url))
        assert timeout > 0
        if ambiguous_reply:
            raise TimeoutError("create reply lost")
        return "page"

    monkeypatch.setattr(browser, "_create_startup_page", create)
    killed = []
    monkeypatch.setattr(browser, "_kill_process_tree", killed.append)
    monkeypatch.setattr(browser, "_query_chrome_version", lambda port: None)
    monkeypatch.setattr(browser.registry, "register_instance", lambda **kw: None)
    monkeypatch.setattr(browser.registry, "lookup", lambda *args: None)
    monkeypatch.setattr(_session, "process_info", lambda pid: None)
    monkeypatch.setattr(
        _session,
        "read",
        lambda sid: {
            "session_id": sid,
            "transport": "cdp",
            "automation_target_id": "page",
        },
    )
    monkeypatch.setattr(_session, "write", lambda record: None)
    result = browser.browser_start(temp=True, headless=True, startup_timeout=3)
    assert len(launches) == 1 and queries == [9355, 9355]
    assert launches[0]["start_url"] == ""
    assert launches[0]["override_default_args"]["--no-startup-window"] == ""
    assert creations == [(9355, "ready", "about:blank")] and killed == []
    if ambiguous_reply:
        assert result["error_code"] == "transient" and not result["connected"]
        assert result["pid"] == 1234 and not result["browser_closed"]
        assert "create reply lost" in result["error"]
        return
    assert result["connected"] and result["session_id"] == "cdp-ready"
    assert result["automation_target_id"] == "page"


def test_restart_options_keep_launch_path_separate_from_runtime_clone(monkeypatch):
    saved = []
    observed = {
        "pid": 1234,
        "process_created": 1.0,
        "chrome_path": "/temporary/code_sign_clone/Chrome",
        "launch_args": [],
    }
    monkeypatch.setattr(_session, "process_info", lambda pid: observed)
    monkeypatch.setattr(
        _session,
        "read",
        lambda sid: {
            "session_id": sid,
            "transport": "cdp",
            "automation_target_id": "page",
        },
    )
    monkeypatch.setattr(_session, "write", lambda record: saved.append(record))
    monkeypatch.setattr(browser.registry, "lookup", lambda *args: None)
    monkeypatch.setattr(browser, "_query_chrome_version", lambda port: None)
    result = browser._describe_cdp(
        {"port": 9355, "pid": 1234},
        start_options={"chrome_path": "/Applications/Chrome"},
        guid="ready",
    )
    assert saved[0]["chrome_path"] == observed["chrome_path"]
    assert saved[0]["start_options"]["chrome_path"] == "/Applications/Chrome"
    assert result["launch_chrome_path"] == "/Applications/Chrome"


def test_mac_clone_requires_same_birth_profile_and_live_session(monkeypatch):
    monkeypatch.setattr(_session.sys, "platform", "darwin")
    from ai_dev_browser.core import port

    monkeypatch.setattr(port, "_query_chrome_guid", lambda number: "same")
    record = {
        "pid": 1234,
        "process_created": 1.0,
        "chrome_path": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "start_options": {
            "chrome_path": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        },
        "user_data_dir": "/test/owned-profile",
        "session_id": "cdp-same",
        "port": 9355,
    }
    current = {
        "pid": 1234,
        "process_created": 1.0,
        "chrome_path": "/private/var/folders/test/X/com.google.Chrome.code_sign_clone/code_sign_clone.ABC123/Google Chrome.app.bundle/Contents/MacOS/Google Chrome",
        "launch_args": ["Google Chrome", "--user-data-dir=/test/owned-profile"],
    }
    monkeypatch.setattr(_session, "process_info", lambda pid: current)
    assert _session.same_process(record)
    current["process_created"] = 2.0
    assert not _session.same_process(record)
    current["process_created"] = 1.0
    current["launch_args"] = ["Google Chrome", "--user-data-dir=/different"]
    assert not _session.same_process(record)
    current["launch_args"] = ["Google Chrome", "--user-data-dir=/test/owned-profile"]
    monkeypatch.setattr(port, "_query_chrome_guid", lambda number: "replacement")
    assert not _session.same_process(record)
    monkeypatch.setattr(port, "_query_chrome_guid", lambda number: "same")
    current["chrome_path"] = "/private/var/folders/test/unrelated/Google Chrome"
    assert not _session.same_process(record)
    # Runtime observation can return from the clone to the original image.
    record["chrome_path"] = (
        "/private/var/folders/test/X/com.google.Chrome.code_sign_clone/code_sign_clone.ABC123/Google Chrome.app.bundle/Contents/MacOS/Google Chrome"
    )
    current["chrome_path"] = record["start_options"]["chrome_path"]
    assert _session.same_process(record)
    current["process_created"] = 2.0
    assert not _session.same_process(record)
    current["process_created"] = 1.0
    monkeypatch.setattr(port, "_query_chrome_guid", lambda number: "replacement")
    assert not _session.same_process(record)
