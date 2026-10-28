"""Run the real shared-session workflow in an isolated branded Chrome image.

The machine policy was built with a fixture signing key. Only this container's
empty /profile is used; no developer/user Chrome installation is modified.
"""

import functools
import os
import shutil
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest


class QuietAssets(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def main():
    required = ("Xvfb", "openbox", "xprop", "xdotool", "xclip")
    missing = [tool for tool in required if not shutil.which(tool)]
    if missing:
        raise RuntimeError("Managed native acceptance requires: " + ", ".join(missing))
    server = ThreadingHTTPServer(
        ("127.0.0.1", 8080),
        functools.partial(QuietAssets, directory="/opt/browser/extension"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    os.environ["AI_DEV_BROWSER_MANAGED_EXTENSION_PROFILE"] = "/profile/chrome"
    try:
        return pytest.main(
            [
                "-q",
                "--asyncio-mode=auto",
                "-o",
                "asyncio_default_fixture_loop_scope=function",
                "-o",
                "cache_dir=/tmp/managed-pytest-cache",
                "tests/integration/test_extension_frames_live.py",
                "tests/integration/test_browser_session_live.py",
                "tests/integration/test_remote_window_live.py",
                "tests/integration/test_browser_files_live.py",
                "tests/integration/test_worker_managed_status_live.py",
                "--basetemp",
                os.environ.get(
                    "AI_DEV_BROWSER_MANAGED_RESULTS", "/tmp/managed-results"
                ),
            ]
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    raise SystemExit(main())
