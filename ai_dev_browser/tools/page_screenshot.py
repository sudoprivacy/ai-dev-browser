"""AUTO-GENERATED from ai_dev_browser.core — page_screenshot
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import page_screenshot as _core_func

from .._cli import as_cli, wrap_core


page_screenshot = as_cli()(wrap_core(_core_func, "path"))

if __name__ == "__main__":
    page_screenshot.cli_main()
