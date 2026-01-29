"""JavaScript dialog handling operations.

Handles browser dialogs: alert(), confirm(), prompt(), and beforeunload.
"""

import asyncio
from typing import Callable, Optional

import nodriver
import nodriver.cdp.page as page_cdp


async def handle_dialog(
    tab: nodriver.Tab,
    accept: bool = True,
    prompt_text: Optional[str] = None,
) -> bool:
    """Handle a JavaScript dialog immediately.

    Args:
        tab: Tab instance
        accept: True to accept/OK, False to dismiss/Cancel
        prompt_text: Optional text to enter for prompt() dialogs

    Returns:
        True if dialog was handled, False if no dialog present

    Raises:
        Exception: If dialog handling fails for reasons other than no dialog
    """
    try:
        if prompt_text is not None:
            await tab.send(
                page_cdp.handle_java_script_dialog(
                    accept=accept, prompt_text=prompt_text
                )
            )
        else:
            await tab.send(page_cdp.handle_java_script_dialog(accept=accept))
        return True
    except Exception as e:
        if "No dialog is showing" in str(e):
            return False
        raise


async def wait_for_dialog(
    tab: nodriver.Tab,
    accept: bool = True,
    prompt_text: Optional[str] = None,
    timeout: float = 5.0,
) -> bool:
    """Wait for a dialog to appear and handle it.

    Args:
        tab: Tab instance
        accept: True to accept/OK, False to dismiss/Cancel
        prompt_text: Optional text to enter for prompt() dialogs
        timeout: Maximum time to wait for dialog in seconds

    Returns:
        True if dialog appeared and was handled, False if timeout
    """
    elapsed = 0.0
    interval = 0.2

    while elapsed < timeout:
        if await handle_dialog(tab, accept=accept, prompt_text=prompt_text):
            return True
        await asyncio.sleep(interval)
        elapsed += interval

    return False


async def setup_auto_dialog_handler(
    tab: nodriver.Tab,
    accept: bool = True,
    callback: Optional[Callable[[page_cdp.JavascriptDialogOpening], None]] = None,
) -> None:
    """Set up automatic dialog handling for a tab.

    This enables Page events and registers a handler that automatically
    accepts/dismisses dialogs as they appear. Useful for pages that
    trigger beforeunload dialogs during navigation.

    Args:
        tab: Tab instance
        accept: True to auto-accept, False to auto-dismiss
        callback: Optional callback for when dialog is handled
    """
    # Enable page events
    await tab.send(page_cdp.enable())

    async def on_dialog(event: page_cdp.JavascriptDialogOpening):
        try:
            await tab.send(page_cdp.handle_java_script_dialog(accept=accept))
            if callback:
                callback(event)
        except Exception:
            pass  # Dialog might already be handled

    # Register the handler
    tab.add_handler(page_cdp.JavascriptDialogOpening, on_dialog)
