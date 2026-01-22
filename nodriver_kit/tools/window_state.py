"""Set window state (maximize, minimize, fullscreen).

CLI:
    python -m nodriver_kit.tools.window_state --state maximize

Python:
    from nodriver_kit.tools import window_state
    result = await window_state(tab, state="maximize")
"""

from nodriver_kit.core import set_window_state
from ._cli import as_cli


@as_cli()
async def window_state(tab, state: str) -> dict:
    """Set the window state.

    Args:
        tab: Browser tab
        state: Window state ("normal", "minimize", "maximize", "fullscreen")

    Returns:
        {"state": ...}
    """
    try:
        await set_window_state(tab, state=state)
        return {"state": state}
    except Exception as e:
        return {"error": f"Set window state failed: {e}"}


if __name__ == "__main__":
    window_state.cli_main()
