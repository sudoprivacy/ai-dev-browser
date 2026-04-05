"""AUTO-GENERATED from ai_dev_browser.core — window_set
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import window_set as _core_func

from .._cli import as_cli, wrap_core


window_set = as_cli()(wrap_core(_core_func, "success"))

if __name__ == "__main__":
    window_set.cli_main()
