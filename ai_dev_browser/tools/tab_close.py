"""AUTO-GENERATED from ai_dev_browser.core.tabs.close_tab
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core.tabs import close_tab as _core_func

from .._cli import as_cli, wrap_core


tab_close = as_cli()(wrap_core(_core_func, "closed"))

if __name__ == "__main__":
    tab_close.cli_main()
