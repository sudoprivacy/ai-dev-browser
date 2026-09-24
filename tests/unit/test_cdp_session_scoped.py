"""cdp_send warns when a method's effect is session-scoped (issue #7).

Browser.setDownloadBehavior via cdp_send silently dropped downloadPath — the
session that set it closed before the next call's click, and CDP returned a bare
success. The warning stops that from reading as a lasting change and names the
durable tool.
"""

from __future__ import annotations

from ai_dev_browser.core.cdp import _SESSION_SCOPED_METHODS, _session_scoped_note


def test_download_behavior_warns_and_points_at_download_link():
    note = _session_scoped_note("Browser.setDownloadBehavior")
    assert note and "does NOT persist" in note
    assert "download_link" in note  # names the durable tool


def test_case_insensitive_and_page_variant():
    assert _session_scoped_note("browser.setdownloadbehavior") is not None
    assert _session_scoped_note("Page.setDownloadBehavior") is not None


def test_emulation_overrides_warn_with_their_durable_tool():
    assert "window_set" in (
        _session_scoped_note("Emulation.setDeviceMetricsOverride") or ""
    )
    assert "--timezone" in (_session_scoped_note("Emulation.setTimezoneOverride") or "")
    assert "--geo" in (_session_scoped_note("Emulation.setGeolocationOverride") or "")
    assert "--locale" in (_session_scoped_note("Emulation.setLocaleOverride") or "")


def test_benign_methods_do_not_warn():
    assert _session_scoped_note("Browser.getVersion") is None
    assert _session_scoped_note("DOM.getDocument") is None
    assert _session_scoped_note("Page.navigate") is None


def test_every_mapped_method_produces_a_full_sentence():
    for key in _SESSION_SCOPED_METHODS:
        note = _session_scoped_note(key)
        assert note and note.startswith("This effect is bound to the CDP session")
