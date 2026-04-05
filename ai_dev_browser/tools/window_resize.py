"""AUTO-GENERATED from ai_dev_browser.core — window_resize
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import window_resize as _core_func

from .._cli import as_cli, wrap_core


window_resize = as_cli()(wrap_core(_core_func, "resized"))

if __name__ == "__main__":
    window_resize.cli_main()
