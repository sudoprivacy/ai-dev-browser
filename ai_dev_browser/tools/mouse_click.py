"""AUTO-GENERATED from ai_dev_browser.core.mouse.mouse_click
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core.mouse import mouse_click as _core_func

from .._cli import as_cli, wrap_core


mouse_click = as_cli()(wrap_core(_core_func, "clicked"))

if __name__ == "__main__":
    mouse_click.cli_main()
