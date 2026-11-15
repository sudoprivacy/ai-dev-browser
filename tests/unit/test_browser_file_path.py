"""Native path spelling cannot bypass the existing owned file checks."""

import os

import pytest

from ai_dev_browser.remote.control import ControlError
from ai_dev_browser.remote.files import BrowserFiles


def test_native_browser_path_represents_exact_same_verified_owned_file(tmp_path):
    files = BrowserFiles(tmp_path / "files")
    item = files.receive("original.txt", b"original content")
    original = files.path(item["id"], kind="upload")
    native = files.browser_path(item["id"], kind="upload")
    assert native == ("\\\\?\\" + str(original) if os.name == "nt" else str(original))
    assert original.read_bytes() == b"original content"
    original.write_bytes(b"changed unapproved content")
    with pytest.raises(ControlError, match="^browser_file_changed$"):
        files.browser_path(item["id"], kind="upload")
    with pytest.raises(ControlError, match="^browser_file_not_found$"):
        files.browser_path("../other", kind="upload")
