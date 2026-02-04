"""Click element by ref from find()."""

from ai_dev_browser.core.ax import click_ref as core_click_ref

from .._cli import as_cli, wrap_core


click_by_ref = as_cli()(wrap_core(core_click_ref, "clicked"))

if __name__ == "__main__":
    click_by_ref.cli_main()
