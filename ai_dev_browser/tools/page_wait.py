"""AUTO-GENERATED from ai_dev_browser.core.navigation.wait_for_load
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core.navigation import wait_for_load as _core_func

from .._cli import as_cli, wrap_core


page_wait = as_cli()(wrap_core(_core_func, "ready"))

if __name__ == "__main__":
    page_wait.cli_main()
