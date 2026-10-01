"""AUTO-GENERATED from ai_dev_browser.core — page_record_stop
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import page_record_stop as _core_func

from .._cli import as_cli, wrap_core


page_record_stop = as_cli(requires_tab=False)(wrap_core(_core_func, "saved"))

if __name__ == "__main__":
    page_record_stop.cli_main()
