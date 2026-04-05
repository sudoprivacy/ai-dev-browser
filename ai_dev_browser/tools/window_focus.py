"""AUTO-GENERATED from ai_dev_browser.core — window_focus
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import window_focus as _core_func

from .._cli import as_cli, wrap_core


window_focus = as_cli()(wrap_core(_core_func, "focused"))

if __name__ == "__main__":
    window_focus.cli_main()
