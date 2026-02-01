"""Find elements on the page."""

from ai_dev_browser.core import find_element_info

from .._cli import as_cli, wrap_core


element_find = as_cli()(wrap_core(find_element_info, "found"))

if __name__ == "__main__":
    element_find.cli_main()
