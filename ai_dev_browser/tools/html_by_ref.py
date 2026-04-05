"""AUTO-GENERATED from ai_dev_browser.core — html_by_ref
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import html_by_ref as _core_func

from .._cli import as_cli, wrap_core


html_by_ref = as_cli()(wrap_core(_core_func, "html"))

if __name__ == "__main__":
    html_by_ref.cli_main()
