"""AUTO-GENERATED from ai_dev_browser.core — tab_new
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import tab_new as _core_func

from .._cli import as_cli, wrap_core


tab_new = as_cli()(wrap_core(_core_func, "tab_id"))

if __name__ == "__main__":
    tab_new.cli_main()
