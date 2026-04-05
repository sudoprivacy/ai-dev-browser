"""AUTO-GENERATED from ai_dev_browser.core — cloudflare_verify
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import cloudflare_verify as _core_func

from .._cli import as_cli, wrap_core


cloudflare_verify = as_cli()(wrap_core(_core_func, "verified"))

if __name__ == "__main__":
    cloudflare_verify.cli_main()
