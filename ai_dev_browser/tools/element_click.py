"""Click an element on the page."""

from ai_dev_browser.core import click
from .._cli import as_cli, wrap_core

# True SSOT: parameters defined once in core.click, CLI inherits automatically
element_click = as_cli()(wrap_core(click, "clicked"))

if __name__ == "__main__":
    element_click.cli_main()
