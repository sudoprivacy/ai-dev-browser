"""AUTO-GENERATED from ai_dev_browser.core — page_goto
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import page_goto as _core_func

from .._cli import as_cli, wrap_core


page_goto = as_cli()(wrap_core(_core_func, "success"))

if __name__ == "__main__":
    page_goto.cli_main()
