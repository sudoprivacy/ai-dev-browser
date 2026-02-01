"""Verify and bypass Cloudflare challenge."""

from ai_dev_browser.core import verify_cloudflare

from .._cli import as_cli, wrap_core


cf_verify = as_cli()(wrap_core(verify_cloudflare, "verified"))

if __name__ == "__main__":
    cf_verify.cli_main()
