"""Cloudflare bypass wrapper.

Wraps nodriver's native tab.verify_cf() for reliable Cloudflare Turnstile bypass.
Requires: pip install opencv-python

Usage:
    from nodriver_kit import verify_cloudflare

    success = await verify_cloudflare(tab)
"""

import logging

logger = logging.getLogger(__name__)


async def verify_cloudflare(
    tab, max_retries: int = 5, initial_wait: float = 2.0, **kwargs
) -> bool:
    """
    Verify and bypass Cloudflare challenge using nodriver's native verify_cf.

    This is a thin wrapper around tab.verify_cf() that provides a consistent API
    and handles exceptions gracefully.

    Args:
        tab: nodriver Tab object
        max_retries: Max retry attempts (we retry the verify_cf call)
        initial_wait: Seconds to wait before first attempt (for CF to load)
        **kwargs: Additional arguments (ignored for compatibility)

    Returns:
        True if verification succeeded or no challenge present, False otherwise

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
            return True
        except Exception as e:
            error_msg = str(e).lower()
            # "no cf was found" means no challenge present - that's success
            if "no cf" in error_msg or "not found" in error_msg:
                logger.debug("No Cloudflare challenge detected")
                return True
            if attempt < max_retries - 1:
                logger.debug(f"CF attempt {attempt + 1} failed: {e}, retrying...")
                # Longer wait between retries to let CF reset
                await asyncio.sleep(2)
            else:
                logger.warning(
                    f"Cloudflare verification failed after {max_retries} attempts: {e}"
                )
    return False


# Backward compatibility alias
CFVerify = None  # Deprecated, use verify_cloudflare() directly
