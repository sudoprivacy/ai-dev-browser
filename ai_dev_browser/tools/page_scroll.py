"""AUTO-GENERATED from ai_dev_browser.core.elements.scroll
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core.elements import scroll as _core_func

from .._cli import as_cli, wrap_core


page_scroll = as_cli()(wrap_core(_core_func, "scrolled"))

if __name__ == "__main__":
    page_scroll.cli_main()
