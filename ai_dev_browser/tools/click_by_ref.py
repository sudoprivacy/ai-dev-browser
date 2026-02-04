"""AUTO-GENERATED from ai_dev_browser.core.ax.click_by_ref
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core.ax import click_by_ref as _core_func

from .._cli import as_cli, wrap_core


click_by_ref = as_cli()(wrap_core(_core_func, "clicked"))

if __name__ == "__main__":
    click_by_ref.cli_main()
