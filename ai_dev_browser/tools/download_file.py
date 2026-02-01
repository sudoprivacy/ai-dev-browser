"""Download a file."""

from ai_dev_browser.core import download_file as core_download_file

from .._cli import as_cli, wrap_core


download_file = as_cli()(wrap_core(core_download_file, "downloaded"))

if __name__ == "__main__":
    download_file.cli_main()
