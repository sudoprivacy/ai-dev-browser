"""AUTO-GENERATED from ai_dev_browser.core — tab_switch
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import tab_switch as _core_func

from .._cli import as_cli, wrap_core


tab_switch = as_cli()(wrap_core(_core_func, "switched"))

if __name__ == "__main__":
    tab_switch.cli_main()
