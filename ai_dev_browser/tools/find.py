"""Find elements on the page - the main discovery tool for AI."""

from ai_dev_browser.core.snapshot import find as core_find

from .._cli import as_cli, wrap_core


find = as_cli()(wrap_core(core_find, "elements"))

if __name__ == "__main__":
    find.cli_main()
