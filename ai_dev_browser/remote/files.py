"""Host-owned uploads and downloads for one isolated browser profile.

The host authenticates requests and holds the profile lease. Callers receive
opaque file IDs and metadata; filesystem paths stay inside the host. This
module does not select users, publish URLs, or modify a running Chrome profile.
"""

import hashlib
import json
import os
import pathlib
import re
import tempfile
import time
import uuid

from ..core._session import profile_processes
from .control import ControlError


class BrowserFiles:
    def __init__(self, root, *, max_file_bytes=16 * 1024 * 1024):
        if type(max_file_bytes) is not int or max_file_bytes < 1:
            raise ValueError("max_file_bytes must be positive")
        supplied = pathlib.Path(root).absolute()
        if supplied.is_symlink():
            raise ControlError("browser_files_invalid_directory")
        supplied.mkdir(parents=True, exist_ok=True)
        self.root = supplied.resolve()
        self.max_file_bytes = max_file_bytes
        self.uploads = self.root / "uploads"
        self.downloads = self.root / "downloads"
        for directory in (self.uploads, self.downloads):
            if directory.is_symlink():
                raise ControlError("browser_files_invalid_directory")
            directory.mkdir(exist_ok=True)
        self._index_path = self.root / "file-index.json"
        self._index = {}
        self._settling = {}
        if self._index_path.exists():
            try:
                if (
                    self._index_path.is_symlink()
                    or self._index_path.stat().st_size > 1024 * 1024
                ):
                    raise ValueError
                data = json.loads(self._index_path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or len(data) > 4096:
                    raise ValueError
                for file_id, entry in data.items():
                    if not re.fullmatch(r"[0-9a-f]{32}", file_id) or not isinstance(
                        entry, dict
                    ):
                        raise ValueError
                    if entry.get("kind") not in ("upload", "download"):
                        raise ValueError
                    self._validate_name(entry.get("name"))
                    if (
                        type(entry.get("bytes")) is not int
                        or not 0 <= entry["bytes"] <= self.max_file_bytes
                    ):
                        raise ValueError
                    if not re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", "")):
                        raise ValueError
                self._index = data
            except (OSError, ValueError, TypeError, ControlError):
                raise ControlError("browser_files_store_requires_recovery") from None

    @staticmethod
    def _validate_name(name):
        if (
            not isinstance(name, str)
            or not name
            or len(name.encode("utf-8")) > 240
            or any(character in name for character in '<>:"/\\|?*')
            or any(ord(character) < 32 for character in name)
            or name.endswith((".", " "))
            or name in (".", "..")
            or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", name)
        ):
            raise ControlError("browser_files_invalid_name")

    def _save(self):
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=self.root, prefix=".files-", delete=False
        ) as output:
            temporary = pathlib.Path(output.name)
            try:
                os.chmod(temporary, 0o600)
                json.dump(self._index, output)
                output.flush()
                os.fsync(output.fileno())
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            os.replace(temporary, self._index_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _metadata(self, file_id):
        entry = self._index[file_id]
        return {
            "id": file_id,
            **{key: entry[key] for key in ("name", "bytes", "sha256", "kind")},
        }

    def _check_directories(self):
        if self.root.resolve() != self.root or any(
            directory.is_symlink() or directory.resolve().parent != self.root
            for directory in (self.uploads, self.downloads)
        ):
            raise ControlError("browser_files_invalid_directory")

    def receive(self, name: str, data: bytes):
        """Stage one authenticated upload; the host enforces its request limit too."""
        self._validate_name(name)
        self._check_directories()
        if not isinstance(data, bytes):
            raise ControlError("browser_files_invalid_upload")
        if len(data) > self.max_file_bytes:
            raise ControlError("browser_files_too_large")
        if len(self._index) >= 4096:
            raise ControlError("browser_files_store_full")
        file_id = uuid.uuid4().hex
        directory = self.uploads / file_id
        directory.mkdir(mode=0o700)
        path = directory / name
        with path.open("xb") as output:
            os.chmod(path, 0o600)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        self._index[file_id] = {
            "kind": "upload",
            "name": name,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        self._save()
        return self._metadata(file_id)

    def path(self, file_id, *, kind=None):
        """Resolve a known file, rejecting changed content and symbolic links."""
        self._check_directories()
        entry = self._index.get(file_id) if isinstance(file_id, str) else None
        if not entry or (kind is not None and entry["kind"] != kind):
            raise ControlError("browser_file_not_found")
        directory = (
            self.uploads / file_id if entry["kind"] == "upload" else self.downloads
        )
        path = directory / entry["name"]
        try:
            if directory.is_symlink() or path.is_symlink() or not path.is_file():
                raise ValueError
            if (
                not path.resolve().is_relative_to(self.root)
                or path.stat().st_size != entry["bytes"]
            ):
                raise ValueError
            if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
                raise ValueError
        except (OSError, ValueError):
            raise ControlError("browser_file_changed") from None
        return path

    def collect_downloads(self, *, settle_seconds=0.5):
        """List completed Chrome downloads; partial and changing files stay hidden."""
        self._check_directories()
        known = {
            (entry["name"], entry["bytes"], entry["sha256"]): file_id
            for file_id, entry in self._index.items()
            if entry["kind"] == "download"
        }
        result = []
        for path in sorted(self.downloads.iterdir()):
            if len(result) >= 100:
                break
            if (
                path.is_symlink()
                or not path.is_file()
                or path.name.endswith((".crdownload", ".tmp", ".part"))
            ):
                continue
            try:
                self._validate_name(path.name)
                before = path.stat()
                if before.st_size > self.max_file_bytes:
                    continue
                fingerprint = (before.st_size, before.st_mtime_ns)
                previous = self._settling.get(path.name)
                if not previous or previous[0] != fingerprint:
                    self._settling[path.name] = (fingerprint, time.monotonic())
                    continue
                if time.monotonic() - previous[1] < settle_seconds:
                    continue
                if len(previous) == 3:
                    result.append(self._metadata(previous[2]))
                    continue
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                after = path.stat()
                if fingerprint != (after.st_size, after.st_mtime_ns):
                    continue
                key = (path.name, after.st_size, digest)
                file_id = known.get(key)
                if file_id is None:
                    if len(self._index) >= 4096:
                        raise ControlError("browser_files_store_full")
                    file_id = uuid.uuid4().hex
                    self._index[file_id] = {
                        "kind": "download",
                        "name": path.name,
                        "bytes": after.st_size,
                        "sha256": digest,
                    }
                    self._save()
                    known[key] = file_id
                self._settling[path.name] = (fingerprint, previous[1], file_id)
                result.append(self._metadata(file_id))
            except (OSError, ValueError):
                continue
        return result

    def configure_managed_profile(self, profile):
        """Configure this owned download directory before Chrome starts.

        The host must already hold the profile's exclusive lease. User Chrome
        profiles and running profiles must use their existing settings instead.
        Only download preferences are changed; installed extensions are retained.
        """
        profile = pathlib.Path(profile).resolve()
        if profile_processes(profile):
            raise ControlError("managed_browser_profile_process_still_running")
        default = profile / "Default"
        if default.is_symlink():
            raise ControlError("browser_files_invalid_directory")
        default.mkdir(parents=True, exist_ok=True)
        preferences = default / "Preferences"
        if preferences.is_symlink():
            raise ControlError("browser_files_invalid_directory")
        try:
            data = (
                json.loads(preferences.read_text(encoding="utf-8"))
                if preferences.exists()
                else {}
            )
            if not isinstance(data, dict) or not isinstance(
                data.get("download", {}), dict
            ):
                raise TypeError
        except (OSError, ValueError, TypeError):
            raise ControlError("browser_profile_preferences_require_recovery") from None
        data.setdefault("download", {}).update(
            default_directory=str(self.downloads), prompt_for_download=False
        )
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=default, prefix=".download-", delete=False
        ) as output:
            temporary = pathlib.Path(output.name)
            os.chmod(temporary, 0o600)
            json.dump(data, output)
        try:
            os.replace(temporary, preferences)
        finally:
            temporary.unlink(missing_ok=True)
