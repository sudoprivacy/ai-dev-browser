"""AUTO-GENERATED from ai_dev_browser.core — hover_by_ref
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import hover_by_ref as _core_func

from .._cli import as_cli, wrap_core


hover_by_ref = as_cli()(wrap_core(_core_func, "hovered"))

if __name__ == "__main__":
    hover_by_ref.cli_main()
