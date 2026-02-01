"""Find elements by XPath."""

from ai_dev_browser.core import find_by_xpath

from .._cli import as_cli, wrap_core


element_xpath = as_cli()(wrap_core(find_by_xpath, "found"))

if __name__ == "__main__":
    element_xpath.cli_main()
