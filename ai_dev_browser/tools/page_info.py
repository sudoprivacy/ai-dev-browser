"""AUTO-GENERATED from ai_dev_browser.core.page.get_page_info
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core.page import get_page_info as _core_func

from .._cli import as_cli, wrap_core


page_info = as_cli()(wrap_core(_core_func, "url"))

if __name__ == "__main__":
    page_info.cli_main()
