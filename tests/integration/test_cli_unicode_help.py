"""Regression: CLI `--help` must not crash on hosts whose stdout
encoding can't render every char in our docstrings.

Pre-fix: every master push between v0.10.2 and v0.11.0 had
`test (windows-latest)` red because docstrings contain `→` (e.g.
`headless` resolution rules in browser_start). On Windows GitHub
runners, stdout defaults to cp1252 and `argparse._print_message`
crashes with UnicodeEncodeError before --help can return.

The fix is one edit at the shared CLI entry (`cli_main`):
reconfigure stdout+stderr to UTF-8. This must be encoding-safe for
ANY future docstring char, not just the `→` we hit this time —
hence the cp1252 forced-codec test below rather than just
scrubbing the arrow.
"""

import os
import subprocess
import sys

import pytest


SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)


@pytest.fixture(autouse=True)
def _integration_guard():
    if SKIP_INTEGRATION:
        pytest.skip("SKIP_INTEGRATION is set")


def test_help_survives_narrow_stdout_codec():
    """Force the child's stdout/stderr to cp1252 (Windows default codec
    on legacy consoles) and confirm `--help` still exits cleanly.

    Pre-fix this crashed with UnicodeEncodeError on the `→` characters
    in browser_start's docstring. The fix reconfigures both streams to
    UTF-8 inside cli_main(); this test checks the reconfigure actually
    wins over PYTHONIOENCODING."""
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    result = subprocess.run(
        [sys.executable, "-m", "ai_dev_browser.tools.browser_start", "--help"],
        env=env,
        capture_output=True,
    )
    assert result.returncode == 0, (
        f"--help under PYTHONIOENCODING=cp1252 should succeed; "
        f"got exit={result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    # Sanity: we got real help output, not silent success
    assert b"usage" in result.stdout.lower() or b"--port" in result.stdout, (
        f"expected argparse help in stdout, got: {result.stdout!r}"
    )
