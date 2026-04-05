"""AUTO-GENERATED from ai_dev_browser.core — storage_set
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import storage_set as _core_func

from .._cli import as_cli, wrap_core


storage_set = as_cli()(wrap_core(_core_func, "set"))

if __name__ == "__main__":
    storage_set.cli_main()
