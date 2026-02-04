"""AUTO-GENERATED from ai_dev_browser.core.tabs.list_tabs
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core.tabs import list_tabs as _core_func

from .._cli import as_cli, wrap_core


tab_list = as_cli()(wrap_core(_core_func, "tabs"))

if __name__ == "__main__":
    tab_list.cli_main()
