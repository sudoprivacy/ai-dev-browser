"""Set download path."""

from ai_dev_browser.core import set_download_path

from .._cli import as_cli, wrap_core


download_path = as_cli()(wrap_core(set_download_path, "path"))

if __name__ == "__main__":
    download_path.cli_main()
