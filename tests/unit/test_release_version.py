"""Reject stale wheel metadata before any release assets can be published."""

from zipfile import ZipFile

import pytest

from scripts.build_release_assets import build_assets


def test_another_tag_on_the_same_commit_cannot_publish_the_old_version(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    with ZipFile(dist / "ai_dev_browser-0.57.0-py3-none-any.whl", "w") as wheel:
        wheel.writestr(
            "ai_dev_browser-0.57.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: ai-dev-browser\nVersion: 0.57.0\n",
        )
    (dist / "ai_dev_browser-0.57.0.tar.gz").write_bytes(b"fixture")
    output = tmp_path / "release-assets"
    with pytest.raises(
        ValueError, match="release 0.57.1 contains wheel version 0.57.0"
    ):
        build_assets(dist, output, "0.57.1")
    assert not output.exists()
