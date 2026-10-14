"""File identity and incomplete-download boundaries on the real filesystem."""

import json

import pytest

from ai_dev_browser.remote.control import ControlError
from ai_dev_browser.remote.files import BrowserFiles


def test_unknown_ids_and_outside_names_cannot_leave_the_store(tmp_path):
    files = BrowserFiles(tmp_path / "owned", max_file_bytes=8)
    for name in ("../foreign", "nested/file", "nested\\file", "CON.txt", "", "a\x00b"):
        with pytest.raises(ControlError, match="invalid_name"):
            files.receive(name, b"value")
    with pytest.raises(ControlError, match="too_large"):
        files.receive("large.txt", b"123456789")
    with pytest.raises(ControlError, match="not_found"):
        files.path("../foreign")
    assert list(files.uploads.iterdir()) == []
    assert not (tmp_path / "foreign").exists()


def test_reconstruction_rejects_changed_upload_content(tmp_path):
    files = BrowserFiles(tmp_path)
    uploaded = files.receive("report.txt", b"original")
    path = files.path(uploaded["id"])
    restored = BrowserFiles(tmp_path)
    assert restored.path(uploaded["id"]).read_bytes() == b"original"
    path.write_bytes(b"tampered")
    with pytest.raises(ControlError, match="file_changed"):
        restored.path(uploaded["id"])


def test_downloads_hide_partial_files_and_fence_replaced_content(tmp_path):
    files = BrowserFiles(tmp_path)
    partial = files.downloads / "report.txt.crdownload"
    partial.write_bytes(b"pending")
    assert not files.collect_downloads(settle_seconds=0)
    completed = files.downloads / "report.txt"
    partial.rename(completed)
    assert not files.collect_downloads(settle_seconds=0)
    first = files.collect_downloads(settle_seconds=0)[0]
    assert files.collect_downloads(settle_seconds=0)[0] == first
    completed.write_bytes(b"replacement")
    assert not files.collect_downloads(settle_seconds=0)
    second = files.collect_downloads(settle_seconds=0)[0]
    assert second["id"] != first["id"] and second["bytes"] == 11
    with pytest.raises(ControlError, match="file_changed"):
        files.path(first["id"])


def test_corrupt_metadata_is_reported_without_resetting_file_data(tmp_path):
    files = BrowserFiles(tmp_path)
    uploaded = files.receive("report.txt", b"preserve this")
    path = files.path(uploaded["id"])
    index = tmp_path / "file-index.json"
    data = json.loads(index.read_text())
    data[uploaded["id"]]["name"] = "../foreign.txt"
    index.write_text(json.dumps(data))
    with pytest.raises(ControlError, match="store_requires_recovery"):
        BrowserFiles(tmp_path)
    assert path.read_bytes() == b"preserve this"
    assert json.loads(index.read_text()) == data
