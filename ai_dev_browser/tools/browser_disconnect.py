"""AUTO-GENERATED from ai_dev_browser.core — browser_disconnect
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import browser_disconnect as _core_func

from .._cli import as_cli, wrap_core_sync


browser_disconnect = as_cli(requires_tab=False)(wrap_core_sync(_core_func, "stopped"))

if __name__ == "__main__":
    browser_disconnect.cli_main()
