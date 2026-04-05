"""AUTO-GENERATED from ai_dev_browser.core — storage_get
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import storage_get as _core_func

from .._cli import as_cli, wrap_core


storage_get = as_cli()(wrap_core(_core_func, "value"))

if __name__ == "__main__":
    storage_get.cli_main()
