"""Locate the bundled bridge extension and produce load instructions.

Chrome 127+ silently ignores the `--load-extension` command-line switch, so the
extension transport can't be auto-activated — it needs a one-time manual "Load
unpacked". This module gives the caller (and, via the failure hint on
`browser_connect --transport extension`, the LLM) the exact on-disk path the
package ships and the steps to relay to the user.
"""

from __future__ import annotations

from pathlib import Path

# Fixed local port the extension's background.js dials and the adb-side bridge
# listens on. Shared convention between JS and Python — keep both in sync.
EXTENSION_BRIDGE_PORT = 9522


def extension_dir() -> Path:
    """Absolute path to the bundled unpacked extension (ships with the wheel)."""
    return Path(__file__).resolve().parent.parent / "extension"


def extension_load_instructions(extension_dir_path: str | None = None) -> str:
    """Step-by-step 'Load unpacked' guidance, with the resolved package path.

    Written to be relayed verbatim by an LLM to its human: Chrome blocks
    command-line loading, so a person must load it once.
    """
    path = extension_dir_path or str(extension_dir())
    return (
        "Extension mode needs the ai-dev-browser bridge extension loaded once, "
        "by hand (Chrome blocks command-line loading). Ask the user to:\n"
        "  1. Open chrome://extensions\n"
        "  2. Turn on 'Developer mode' (top-right)\n"
        "  3. Click 'Load unpacked' and select this folder:\n"
        f"       {path}\n"
        "  4. Keep the extension enabled and Chrome running.\n"
        "Then retry with --transport extension."
    )
