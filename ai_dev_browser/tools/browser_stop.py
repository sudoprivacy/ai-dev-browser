"""AUTO-GENERATED from ai_dev_browser.core.browser.stop_browser
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core.browser import stop_browser as _core_func

from .._cli import as_cli, wrap_core_sync


browser_stop = as_cli(requires_tab=False)(wrap_core_sync(_core_func, "stopped"))

if __name__ == "__main__":
    browser_stop.cli_main()
