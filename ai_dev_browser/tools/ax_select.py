"""Select and click element by accessibility tree ref."""

from ai_dev_browser.core import click_ax_element

from .._cli import as_cli, wrap_core


ax_select = as_cli()(wrap_core(click_ax_element, "clicked"))

if __name__ == "__main__":
    ax_select.cli_main()
