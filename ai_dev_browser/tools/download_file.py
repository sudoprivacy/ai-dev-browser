"""AUTO-GENERATED from ai_dev_browser.core.download.download_file
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core.download import download_file as _core_func

from .._cli import as_cli, wrap_core


download_file = as_cli()(wrap_core(_core_func, "path"))

if __name__ == "__main__":
    download_file.cli_main()
