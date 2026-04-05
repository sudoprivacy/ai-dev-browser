"""AUTO-GENERATED from ai_dev_browser.core — tab_list
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import tab_list as _core_func

from .._cli import as_cli, wrap_core


tab_list = as_cli()(wrap_core(_core_func, "tabs"))

if __name__ == "__main__":
    tab_list.cli_main()
