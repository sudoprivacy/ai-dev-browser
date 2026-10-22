"""Discovery does not amplify socket exhaustion or classify arbitrary JSON."""

import errno

import psutil
import pytest

from ai_dev_browser.core import port


@pytest.mark.parametrize("code", [errno.ENOBUFS, errno.ENOMEM, errno.EMFILE])
def test_inventory_resource_failure_does_not_allocate_probe_sockets(monkeypatch, code):
    def exhausted(**_kwargs):
        raise OSError(code, "owned fixture resource failure")

    def unexpected_probe(*_args, **_kwargs):
        pytest.fail("Resource exhaustion must not trigger active socket probes")

    monkeypatch.setattr(psutil, "net_connections", exhausted)
    monkeypatch.setattr(port, "_fast_listening_check", unexpected_probe)
    with pytest.raises(OSError) as failure:
        port._scan_ports_for_chrome((9222, 9422))
    assert failure.value.errno == code


def test_empty_listener_table_needs_no_active_scan(monkeypatch):
    monkeypatch.setattr(psutil, "net_connections", lambda **_kwargs: [])

    def unexpected_probe(*_args, **_kwargs):
        pytest.fail("An empty listener inventory needs no connection probes")

    monkeypatch.setattr(port, "_fast_listening_check", unexpected_probe)
    assert port.find_debug_chromes((20000, 20004)) == []


@pytest.mark.parametrize(
    "metadata",
    [[], {"Browser": "HTTP fixture"}, {"webSocketDebuggerUrl": 123}],
)
def test_non_browser_metadata_cannot_become_a_debug_target(monkeypatch, metadata):
    monkeypatch.setattr(port, "_query_chrome_version", lambda *_a, **_k: metadata)

    def unexpected_command(*_args, **_kwargs):
        pytest.fail("A service without a browser GUID is not a CDP target")

    monkeypatch.setattr(port, "_query_chrome_cmdline", unexpected_command)
    assert port._resolve_instance(20000) is None
