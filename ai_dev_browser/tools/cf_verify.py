"""Verify and bypass Cloudflare challenge."""

from ai_dev_browser.core.cloudflare import verify_cloudflare
from ._cli import as_cli


@as_cli()
async def cf_verify(tab, max_retries: int = 5) -> dict:
    """Verify and bypass Cloudflare challenge. Requires: pip install opencv-python

    Args:
        tab: Browser tab
        max_retries: Maximum retry attempts
    """
    try:
        success = await verify_cloudflare(tab, max_retries=max_retries)
        if success:
            return {"verified": True}
        else:
            return {"error": "Cloudflare verification failed"}
    except Exception as e:
        return {"error": f"CF verification failed: {e}"}


if __name__ == "__main__":
    cf_verify.cli_main()
