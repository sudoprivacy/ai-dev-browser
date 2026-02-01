"""Emulate window focus for background automation.

Some websites require window focus to render modals, dialogs, and menus.
This enables focus emulation via CDP, making automation work even when
the browser window is in the background.

CLI:
    python -m ai_dev_browser.tools.window_focus_emulation
    python -m ai_dev_browser.tools.window_focus_emulation --enabled false

Python:
    from ai_dev_browser.tools import window_focus_emulation
    await window_focus_emulation(tab)  # Enable
    await window_focus_emulation(tab, enabled=False)  # Disable
"""

from ai_dev_browser.core import set_focus_emulation

from .._cli import as_cli, wrap_core


window_focus_emulation = as_cli()(wrap_core(set_focus_emulation, "enabled"))

if __name__ == "__main__":
    window_focus_emulation.cli_main()
