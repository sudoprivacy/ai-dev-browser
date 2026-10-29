"""Locate the bundled bridge extension and produce load instructions.

Branded Chrome 137+ removes the `--load-extension` command-line switch, so the
extension transport can't be auto-activated — it needs a one-time manual "Load
unpacked". This module gives the caller (and, via the failure hint on
`browser_connect --transport extension`, the LLM) the exact on-disk path the
package ships and the steps to relay to the user.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# Fixed local port the extension's background.js dials and the adb-side bridge
# listens on. Shared convention between JS and Python — keep both in sync.
EXTENSION_BRIDGE_PORT = int(
    os.environ.get("AI_DEV_BROWSER_EXTENSION_BRIDGE_PORT", "9522")
)
if not 1 <= EXTENSION_BRIDGE_PORT <= 65535:
    raise ValueError("AI_DEV_BROWSER_EXTENSION_BRIDGE_PORT must be 1..65535")


def extension_dir() -> Path:
    """Absolute path to the bundled unpacked extension (ships with the wheel)."""
    return Path(__file__).resolve().parent.parent / "extension"


def extension_version_info(loaded_version: str | None) -> dict:
    """Compare a running extension's report with the bundled manifest, not Python."""
    bundled = json.loads(
        (extension_dir() / "manifest.json").read_text(encoding="utf-8")
    )["version"]
    matches = loaded_version == bundled if loaded_version else None
    warning = None
    if matches is not True:
        observed = (
            f"Loaded extension {loaded_version} differs from SDK bundle {bundled}"
            if loaded_version
            else f"Loaded extension version is unknown (SDK bundle {bundled})"
        )
        warning = (
            f"{observed}; compatibility has not been verified. Before page input, "
            "align the Python package and running extension with an ordinary "
            "update/reload in chrome://extensions in the intended profile. "
            f"This SDK's bundle is {extension_dir()}. "
            "Python updates do not reload Chrome's extension. Then use "
            "browser_connect --transport extension and inspect session/profile, "
            "owned target and real visibility before resuming; reload may replace "
            "the session. Keep Chrome and its existing tabs; do not replay "
            "earlier submissions."
        )
    return {
        "extension_version": loaded_version,
        "bundled_extension_version": bundled,
        "extension_version_matches_bundle": matches,
        "extension_warning": warning,
    }


def bridge_version_info(status: dict) -> dict:
    """Report the running daemon's own version; older daemons remain unknown."""
    from .._version import __version__

    version = status.get("bridge_runtime_version")
    matches = version == __version__ if version else None
    warning = None
    if matches is not True:
        warning = (
            f"Running bridge version {version or 'unknown'}; client SDK {__version__}. "
            "Updating Python or reloading the extension does not restart an existing "
            "Python bridge. Inspect bridge_driver_connections (socket count, not "
            "tasks); older bridges cannot report it. Finish controllers/recorders "
            "and coordinate an explicit browser_disconnect --transport extension "
            "then browser_connect --transport extension. Disconnect releases "
            "other controllers too. Keep Chrome/profile/tabs and inspect session, "
            "ownership and visibility afterward; never replay previous input."
        )
    return {
        "bridge_runtime_version": version,
        "bridge_version_matches_client": matches,
        "bridge_started_at": status.get("bridge_started_at"),
        "bridge_message_limit": status.get("bridge_message_limit"),
        "bridge_driver_connections": status.get("bridge_driver_connections"),
        "bridge_warning": warning,
    }


async def query_extension_version(browser, fallback: str | None = None) -> str | None:
    """Read the live extension, including when an older bridge drops hello fields."""
    try:
        state = await query_extension_state(browser.connection)
        version = state.get("extensionVersion")
        return version if isinstance(version, str) else fallback
    except Exception:
        return fallback  # Diagnostics never replace the actual operation's error.


async def query_extension_state(sender) -> dict:
    """Read the existing diagnostic route in its browser or selected-tab scope."""
    from ._transport import OwnershipProtocolError
    from .cdp import _get_cdp_command

    try:
        state = await sender.send(
            _get_cdp_command("AiDevBrowser.debugState", {}), timeout=1
        )
        return state if isinstance(state, dict) else {}
    except OwnershipProtocolError:
        raise  # A consent/identity change takes precedence over visibility advice.
    except Exception:
        return {}  # An older worker may lack this optional diagnostic route.


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
