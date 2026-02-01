"""Wait for an element to appear."""

from ai_dev_browser.core import wait_for_element_with_info

from .._cli import as_cli, wrap_core


element_wait = as_cli()(wrap_core(wait_for_element_with_info, "found"))

if __name__ == "__main__":
    element_wait.cli_main()
