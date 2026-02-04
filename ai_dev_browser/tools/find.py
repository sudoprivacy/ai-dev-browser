"""AUTO-GENERATED from ai_dev_browser.core.snapshot.find
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core.snapshot import find as _core_func

from .._cli import as_cli, wrap_core


find = as_cli()(wrap_core(_core_func, "elements"))

if __name__ == "__main__":
    find.cli_main()
