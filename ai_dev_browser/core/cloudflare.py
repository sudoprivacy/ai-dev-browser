"""Cloudflare Turnstile bypass via OpenCV template matching.

Requires: pip install opencv-python

Usage:
    from ai_dev_browser import cf_verify

    success = await cf_verify(tab)
"""

import logging


logger = logging.getLogger(__name__)


async def cf_verify(
    tab, max_retries: int = 5, initial_wait: float = 2.0, **kwargs
) -> dict:
    """
    Verify and bypass Cloudflare challenge using template matching.

    Uses tab.verify_cf() which takes a page_screenshot, finds the Turnstile
    checkbox via OpenCV template matching, and clicks it.

    Args:
        tab: Tab instance
        max_retries: Max retry attempts
        initial_wait: Seconds to wait before first attempt (for CF to load)
        **kwargs: Additional arguments (ignored for compatibility)

    Returns:
        dict with verified status, attempts, message

    Requires:
        pip install opencv-python
    """
    import asyncio

    # Wait for CF challenge to fully render
    if initial_wait > 0:
        logger.debug(f"Waiting {initial_wait}s for CF challenge to load...")
        await asyncio.sleep(initial_wait)

    for attempt in range(max_retries):
        try:
            logger.debug(f"CF verification attempt {attempt + 1}/{max_retries}")
            await tab.verify_cf()
            logger.info("CF verification succeeded")
            return {
                "verified": True,
                "attempts": attempt + 1,
                "message": "Cloudflare verification succeeded",
            }
        except Exception as e:
            error_msg = str(e).lower()
            # "no cf was found" means no challenge present - that's success
            if "no cf" in error_msg or "not found" in error_msg:
                logger.debug("No Cloudflare challenge detected")
                return {
                    "verified": True,
                    "attempts": attempt + 1,
                    "message": "No Cloudflare challenge detected",
                }
            if attempt < max_retries - 1:
                logger.debug(f"CF attempt {attempt + 1} failed: {e}, retrying...")
                await asyncio.sleep(2)
            else:
                logger.warning(
                    f"Cloudflare verification failed after {max_retries} attempts: {e}"
                )

    return {
        "verified": False,
        "attempts": max_retries,
        "error": f"Cloudflare verification failed after {max_retries} attempts",
    }
