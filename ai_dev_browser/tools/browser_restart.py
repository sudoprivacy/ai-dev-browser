"""AUTO-GENERATED from ai_dev_browser.core — browser_restart
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import browser_restart as _core_func

from .._cli import as_cli, wrap_core_sync


browser_restart = as_cli(requires_tab=False)(wrap_core_sync(_core_func, "restarted"))

if __name__ == "__main__":
    browser_restart.cli_main()
