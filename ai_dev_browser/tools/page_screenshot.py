"""Take a screenshot of the page."""

from ai_dev_browser.core import screenshot

from .._cli import as_cli, wrap_core


page_screenshot = as_cli()(wrap_core(screenshot, "path"))

if __name__ == "__main__":
    page_screenshot.cli_main()
