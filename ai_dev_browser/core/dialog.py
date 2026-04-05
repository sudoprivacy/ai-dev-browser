"""JavaScript dialog handling operations.

Handles browser dialogs: alert(), confirm(), prompt(), and beforeunload.
"""

import asyncio
from collections.abc import Callable

from ai_dev_browser.cdp import page as page_cdp

from ._tab import Tab


async def _handle_dialog(
    tab: Tab,
    accept: bool = True,
    prompt_text: str | None = None,
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


async def _wait_for_dialog(
    tab: Tab,
    accept: bool = True,
    prompt_text: str | None = None,
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
        if await _handle_dialog(tab, accept=accept, prompt_text=prompt_text):
            return True
        await asyncio.sleep(interval)
        elapsed += interval

    return False


async def _setup_auto_dialog_handler(
    tab: Tab,
    accept: bool = True,
    callback: Callable[[page_cdp.JavascriptDialogOpening], None] | None = None,
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


async def page_handle_dialog(
    tab: Tab,
    accept: bool = True,
    prompt_text: str | None = None,
    auto_handle: bool = False,
    wait_timeout: float = 0,
) -> dict:
    """Handle JavaScript dialog with various modes.

    Args:
        tab: Tab instance
        accept: True to accept/OK, False to dismiss/Cancel
        prompt_text: Optional text to enter for prompt() dialogs
        auto_handle: If True, set up automatic handling for future dialogs
        wait_timeout: If > 0, wait this many seconds for a dialog to appear

    Returns:
        dict with success, action, and optional error/message
    """
    # Set up auto-handler if requested
    if auto_handle:
        try:
            await _setup_auto_dialog_handler(tab, accept=accept)
            return {"success": True, "action": "auto_handler_enabled"}
        except Exception as e:
            return {"success": False, "error": "setup_failed", "message": str(e)}

    # If wait_timeout specified, wait for dialog
    if wait_timeout > 0:
        try:
            handled = await _wait_for_dialog(
                tab, accept=accept, prompt_text=prompt_text, timeout=wait_timeout
            )
            if handled:
                return {
                    "success": True,
                    "action": "accepted" if accept else "dismissed",
                }
            return {
                "success": False,
                "error": "timeout",
                "message": f"No dialog appeared within {wait_timeout}s",
            }
        except Exception as e:
            return {"success": False, "error": "unknown", "message": str(e)}

    # Immediate handling
    try:
        handled = await _handle_dialog(tab, accept=accept, prompt_text=prompt_text)
        if handled:
            return {"success": True, "action": "accepted" if accept else "dismissed"}
        return {
            "success": False,
            "error": "no_dialog",
            "message": "No dialog is currently showing",
        }
    except Exception as e:
        return {"success": False, "error": "unknown", "message": str(e)}
