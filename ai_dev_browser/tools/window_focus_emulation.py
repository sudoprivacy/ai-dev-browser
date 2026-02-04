"""AUTO-GENERATED from ai_dev_browser.core.window.set_focus_emulation
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core.window import set_focus_emulation as _core_func

from .._cli import as_cli, wrap_core


window_focus_emulation = as_cli()(wrap_core(_core_func, "set"))

if __name__ == "__main__":
    window_focus_emulation.cli_main()
