"""Build the standalone extension and checksums from the actual PyPI artifacts."""

import argparse
import hashlib
import json
from email.parser import BytesParser
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def build_assets(dist: Path, output: Path, expected_version: str | None = None) -> None:
    wheels = list(dist.glob("*.whl"))
    sdists = list(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError("Expected exactly one wheel and one sdist")
    wheel = wheels[0]
    with ZipFile(wheel) as archive:
        metadata_name = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        version = BytesParser().parsebytes(archive.read(metadata_name))["Version"]
        if expected_version is not None and version != expected_version:
            raise ValueError(
                f"Requested release {expected_version} contains wheel version {version}"
            )
        prefix = "ai_dev_browser/extension/"
        files = {
            name.removeprefix(prefix): archive.read(name)
            for name in archive.namelist()
            if name.startswith(prefix) and not name.endswith("/")
        }
        manifest = json.loads(files["manifest.json"])
        for name in [
            manifest["background"]["service_worker"],
            *manifest["icons"].values(),
        ]:
            if name not in files:
                raise ValueError(f"Bundled extension is missing {name}")
        for name in (
            "core/recording.py",
            "core/_recorder.py",
            "core/_demo.py",
            "tools/page_record_start.py",
            "tools/page_record_stop.py",
            "core/_session.py",
            "core/_browser_guidance.py",
            "core/_extension_lifecycle.py",
            "tools/browser_reconnect.py",
            "tools/browser_restart.py",
            "remote/cdp.py",
            "remote/page.py",
            "remote/page_view.js",
            "remote/vnc.py",
            "remote/worker.py",
            "remote/profile_lease.py",
            "remote/mcp-tools.json",
        ):
            if f"ai_dev_browser/{name}" not in archive.namelist():
                raise ValueError(f"Wheel is missing {name}")

    output.mkdir(parents=True, exist_ok=True)
    extension = output / f"ai_dev_browser-extension-{version}.zip"
    with ZipFile(extension, "w", ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(name, content)
    artifacts = [wheel, sdists[0], extension]
    checksums = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
        for path in artifacts
    ]
    (output / "SHA256SUMS").write_text("".join(checksums), encoding="utf-8")
    print(
        f"Release {version}: wheel, sdist, extension ({len(files)} files), SHA256SUMS"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-version")
    args = parser.parse_args()
    build_assets(args.dist, args.output, args.expected_version)
