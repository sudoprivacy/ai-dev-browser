"""Cloudflare bypass wrapper.

Wraps nodriver's native tab.verify_cf() for reliable Cloudflare Turnstile bypass.
Requires: pip install opencv-python

Usage:
    from nodriver_kit import verify_cloudflare

    success = await verify_cloudflare(tab)
"""

import logging

logger = logging.getLogger(__name__)


async def verify_cloudflare(tab, max_retries: int = 5, **kwargs) -> bool:
    """
    Verify and bypass Cloudflare challenge using nodriver's native verify_cf.

    This is a thin wrapper around tab.verify_cf() that provides a consistent API
    and handles exceptions gracefully.

    Args:
        tab: nodriver Tab object
        max_retries: Max retry attempts (passed to verify_cf)
        **kwargs: Additional arguments (ignored for compatibility)

    Returns:
        True if verification succeeded or no challenge present, False otherwise

    Requires:
        pip install opencv-python
    """
    try:
        await tab.verify_cf(max_attempts=max_retries)
        return True
    except Exception as e:
        error_msg = str(e)
        # "no cf was found" means no challenge present - that's success
        if "no cf" in error_msg.lower() or "not found" in error_msg.lower():
            logger.debug("No Cloudflare challenge detected")
            return True
        logger.warning(f"Cloudflare verification failed: {e}")
        return False


# Backward compatibility alias
CFVerify = None  # Deprecated, use verify_cloudflare() directly
