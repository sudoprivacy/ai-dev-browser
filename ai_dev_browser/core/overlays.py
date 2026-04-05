"""Dismiss backdrop overlays and modal dialogs.

Provides a generic utility to close overlays that block page interactions.
Works across most sites with common overlay patterns.

Usage:
    from ai_dev_browser import dismiss_overlays

    dismissed = await dismiss_overlays(tab)

    # With site-specific selectors (e.g., Angular Material)
    dismissed = await dismiss_overlays(
        tab,
        extra_selectors=['.mat-drawer-backdrop', '.cdk-overlay-backdrop']
    )
"""

import logging


logger = logging.getLogger(__name__)

# Generic selectors that work across most sites
DEFAULT_OVERLAY_SELECTORS = [
    '[class*="backdrop"]',
    '[class*="overlay"]',
    ".modal-backdrop",  # Bootstrap
]


async def _dismiss_overlays(
    tab,
    extra_selectors: list[str] | None = None,
    press_escape: bool = True,
    delay: float = 0.3,
) -> bool:
    """
    Dismiss backdrop overlays and modal dialogs.

    Handles common overlay patterns:
    - Backdrop elements (clicking dismisses them)
    - Modal dialogs (Escape key closes them)

    Args:
        tab: Tab instance
        extra_selectors: Additional CSS selectors for site-specific overlays
            (e.g., ['.mat-drawer-backdrop'] for Angular Material)
        press_escape: Press Escape key to close modal dialogs (default: True)
        delay: Delay in seconds after each action (default: 0.3)

    Returns:
        True if any overlay was dismissed, False otherwise

    Example:
        # Generic usage
        await dismiss_overlays(tab)

        # With Angular Material selectors
        await dismiss_overlays(tab, extra_selectors=[
            '.mat-drawer-backdrop',
            '.cdk-overlay-backdrop'
        ])
    """
    import asyncio

    dismissed = False
    all_selectors = DEFAULT_OVERLAY_SELECTORS.copy()
    if extra_selectors:
        all_selectors.extend(extra_selectors)

    selector_string = ", ".join(all_selectors)

    # Step 1: Click on visible backdrop/overlay elements
    try:
        clicked = await tab.evaluate(
            f"""() => {{
            const backdrops = document.querySelectorAll('{selector_string}');
            for (const backdrop of backdrops) {{
                // Check if element is visible (has layout)
                if (backdrop.offsetParent !== null ||
                    getComputedStyle(backdrop).display !== 'none') {{
                    // Check if it's actually covering the viewport
                    const rect = backdrop.getBoundingClientRect();
                    if (rect.width > 100 && rect.height > 100) {{
                        backdrop.click();
                        return true;
                    }}
                }}
            }}
            return false;
        }}"""
        )
        if clicked:
            logger.debug("Clicked backdrop overlay")
            dismissed = True
            await asyncio.sleep(delay)
    except Exception as e:
        logger.debug(f"Backdrop click failed: {e}")

    # Step 2: Press Escape to close any remaining dialogs
    if press_escape:
        try:
            await tab.send(
                tab._target.browser.connection.send_command(
                    "Input.dispatchKeyEvent",
                    {
                        "type": "keyDown",
                        "key": "Escape",
                        "code": "Escape",
                        "windowsVirtualKeyCode": 27,
                        "nativeVirtualKeyCode": 27,
                    },
                )
            )
            await tab.send(
                tab._target.browser.connection.send_command(
                    "Input.dispatchKeyEvent",
                    {
                        "type": "keyUp",
                        "key": "Escape",
                        "code": "Escape",
                        "windowsVirtualKeyCode": 27,
                        "nativeVirtualKeyCode": 27,
                    },
                )
            )
            logger.debug("Pressed Escape key")
            await asyncio.sleep(delay)
        except Exception as e:
            # Fallback: use JavaScript to dispatch Escape
            logger.debug(f"CDP Escape failed ({e}), trying JS fallback")
            try:
                await tab.evaluate(
                    """() => {
                    document.dispatchEvent(new KeyboardEvent('keydown', {
                        key: 'Escape',
                        code: 'Escape',
                        keyCode: 27,
                        which: 27,
                        bubbles: true
                    }));
                }"""
                )
                await asyncio.sleep(delay)
            except Exception as e2:
                logger.debug(f"JS Escape also failed: {e2}")

    return dismissed
