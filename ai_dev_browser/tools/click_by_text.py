"""Click element by text content."""

from ai_dev_browser.core.elements import click_text as core_click_text

from .._cli import as_cli, wrap_core


click_by_text = as_cli()(wrap_core(core_click_text, "clicked"))

if __name__ == "__main__":
    click_by_text.cli_main()
