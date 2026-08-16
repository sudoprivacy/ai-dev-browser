"""AUTO-GENERATED from ai_dev_browser.core — download_link
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import download_link as _core_func

from .._cli import as_cli, wrap_core


download_link = as_cli()(wrap_core(_core_func, "downloaded"))

if __name__ == "__main__":
    download_link.cli_main()
