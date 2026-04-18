"""AUTO-GENERATED from ai_dev_browser.core — find_by_html_id
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import find_by_html_id as _core_func

from .._cli import as_cli, wrap_core


find_by_html_id = as_cli()(wrap_core(_core_func, "found"))

if __name__ == "__main__":
    find_by_html_id.cli_main()
