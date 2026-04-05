"""AUTO-GENERATED from ai_dev_browser.core — page_find
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import page_find as _core_func

from .._cli import as_cli, wrap_core


page_find = as_cli()(wrap_core(_core_func, "elements"))

if __name__ == "__main__":
    page_find.cli_main()
