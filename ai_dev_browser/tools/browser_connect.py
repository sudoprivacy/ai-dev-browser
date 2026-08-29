"""AUTO-GENERATED from ai_dev_browser.core — browser_connect
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import browser_connect as _core_func

from .._cli import as_cli, wrap_core


browser_connect = as_cli(requires_tab=False)(wrap_core(_core_func, "connected"))

if __name__ == "__main__":
    browser_connect.cli_main()
