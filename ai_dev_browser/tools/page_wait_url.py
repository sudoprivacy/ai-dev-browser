"""AUTO-GENERATED from ai_dev_browser.core — page_wait_url
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import page_wait_url as _core_func

from .._cli import as_cli, wrap_core


page_wait_url = as_cli()(wrap_core(_core_func, "matched"))

if __name__ == "__main__":
    page_wait_url.cli_main()
