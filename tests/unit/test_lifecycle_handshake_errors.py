"""Guard the cold-start error observed on the actual Ubuntu release gate."""

import ai_dev_browser.core.browser as browser
from ai_dev_browser.core import _session


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


def test_launch_waits_for_identity_on_the_same_process(monkeypatch):
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
    assert result["connected"] and result["session_id"] == "cdp-ready"
    assert len(launches) == 1 and queries == [9355, 9355]
