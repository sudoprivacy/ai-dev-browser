"""AUTO-GENERATED from ai_dev_browser.core — login_interactive
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import login_interactive as _core_func

from .._cli import as_cli, wrap_core_sync


login_interactive = as_cli(requires_tab=False)(wrap_core_sync(_core_func, "success"))

if __name__ == "__main__":
    login_interactive.cli_main()
