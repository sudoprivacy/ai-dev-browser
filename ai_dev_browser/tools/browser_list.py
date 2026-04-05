"""AUTO-GENERATED from ai_dev_browser.core — browser_list
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import browser_list as _core_func

from .._cli import as_cli, wrap_core_sync


browser_list = as_cli(requires_tab=False)(wrap_core_sync(_core_func, "count"))

if __name__ == "__main__":
    browser_list.cli_main()
