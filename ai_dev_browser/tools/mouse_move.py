"""AUTO-GENERATED from ai_dev_browser.core — mouse_move
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import mouse_move as _core_func

from .._cli import as_cli, wrap_core


mouse_move = as_cli()(wrap_core(_core_func, "moved"))

if __name__ == "__main__":
    mouse_move.cli_main()
