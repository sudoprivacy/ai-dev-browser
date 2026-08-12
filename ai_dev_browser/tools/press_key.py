"""AUTO-GENERATED from ai_dev_browser.core — press_key
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import press_key as _core_func

from .._cli import as_cli, wrap_core


press_key = as_cli()(wrap_core(_core_func, "pressed"))

if __name__ == "__main__":
    press_key.cli_main()
