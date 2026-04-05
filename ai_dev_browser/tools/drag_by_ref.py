"""AUTO-GENERATED from ai_dev_browser.core.ax.drag_by_ref
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core.ax import drag_by_ref as _core_func

from .._cli import as_cli, wrap_core


drag_by_ref = as_cli()(wrap_core(_core_func, "dragged"))

if __name__ == "__main__":
    drag_by_ref.cli_main()
