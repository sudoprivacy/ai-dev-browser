"""AUTO-GENERATED from ai_dev_browser.core — mouse_drag
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import mouse_drag as _core_func

from .._cli import as_cli, wrap_core


mouse_drag = as_cli()(wrap_core(_core_func, "dragged"))

if __name__ == "__main__":
    mouse_drag.cli_main()
