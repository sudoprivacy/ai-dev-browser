"""AUTO-GENERATED from ai_dev_browser.core — page_discover
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import page_discover as _core_func

from .._cli import as_cli, wrap_core


page_discover = as_cli()(wrap_core(_core_func, "elements"))

if __name__ == "__main__":
    page_discover.cli_main()
