"""AUTO-GENERATED from ai_dev_browser.core.window.set_window_state
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core.window import set_window_state as _core_func

from .._cli import as_cli, wrap_core


window_state = as_cli()(wrap_core(_core_func, "state"))

if __name__ == "__main__":
    window_state.cli_main()
