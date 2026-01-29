"""Handle JavaScript dialogs (alert, confirm, prompt, beforeunload).

Provides functionality to accept or dismiss browser dialogs that would
otherwise block automation scripts.
"""

import asyncio

import nodriver.cdp.page as page_cdp

from .._cli import as_cli


async def setup_auto_dialog_handler(tab, accept: bool = True):
    """Set up automatic dialog handling for a tab.

    This enables Page events and sets up a handler that automatically
    accepts/dismisses dialogs as they appear. Useful for pages that
    trigger beforeunload dialogs during navigation.

    Args:
        tab: Browser tab
        accept: True to auto-accept, False to auto-dismiss
    """
    # Enable page events
    await tab.send(page_cdp.enable())

    # The handler will be called when dialog opens
    async def on_dialog(event: page_cdp.JavascriptDialogOpening):
        try:
            await tab.send(page_cdp.handle_java_script_dialog(accept=accept))
        except Exception:
            pass  # Dialog might already be handled

    # Register the handler
    tab.add_handler(page_cdp.JavascriptDialogOpening, on_dialog)


@as_cli()
async def page_handle_dialog(
    tab,
    accept: bool = True,
    prompt_text: str = None,
    auto_handle: bool = False,
    wait_timeout: float = 0,
) -> dict:
    """Accept or dismiss a JavaScript dialog.

    Handles alert(), confirm(), prompt(), and beforeunload dialogs.

    Args:
        tab: Browser tab
        accept: True to accept/OK, False to dismiss/Cancel
        prompt_text: Optional text to enter for prompt() dialogs
        auto_handle: If True, set up automatic handling for future dialogs
        wait_timeout: If > 0, wait this many seconds for a dialog to appear

    Returns:
        {"success": True} if dialog was handled,
        {"success": False, "error": "..."} if no dialog or error
    """
    # Set up auto-handler if requested
    if auto_handle:
        try:
            await setup_auto_dialog_handler(tab, accept=accept)
            return {"success": True, "action": "auto_handler_enabled"}
        except Exception as e:
            return {"success": False, "error": "setup_failed", "message": str(e)}

    # If wait_timeout specified, poll for dialog
    if wait_timeout > 0:
        elapsed = 0
        interval = 0.2
        while elapsed < wait_timeout:
            try:
                if prompt_text is not None:
                    await tab.send(
                        page_cdp.handle_java_script_dialog(
                            accept=accept, prompt_text=prompt_text
                        )
                    )
                else:
                    await tab.send(page_cdp.handle_java_script_dialog(accept=accept))
                return {
                    "success": True,
                    "action": "accepted" if accept else "dismissed",
                }
            except Exception as e:
                if "No dialog is showing" not in str(e):
                    return {"success": False, "error": "unknown", "message": str(e)}
            await asyncio.sleep(interval)
            elapsed += interval
        return {
            "success": False,
            "error": "timeout",
            "message": f"No dialog appeared within {wait_timeout}s",
        }

    # Immediate handling
    try:
        if prompt_text is not None:
            await tab.send(
                page_cdp.handle_java_script_dialog(
                    accept=accept, prompt_text=prompt_text
                )
            )
        else:
            await tab.send(page_cdp.handle_java_script_dialog(accept=accept))
        return {"success": True, "action": "accepted" if accept else "dismissed"}
    except Exception as e:
        error_msg = str(e)
        if "No dialog is showing" in error_msg:
            return {
                "success": False,
                "error": "no_dialog",
                "message": "No dialog is currently showing",
            }
        return {"success": False, "error": "unknown", "message": error_msg}


if __name__ == "__main__":
    page_handle_dialog.cli_main()
