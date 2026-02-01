"""Handle JavaScript dialogs (alert, confirm, prompt, beforeunload).

Provides functionality to accept or dismiss browser dialogs that would
otherwise block automation scripts.
"""

from ai_dev_browser.core import (
    handle_dialog as core_handle_dialog,
)
from ai_dev_browser.core import (
    setup_auto_dialog_handler as core_setup_auto_dialog_handler,
)
from ai_dev_browser.core import (
    wait_for_dialog as core_wait_for_dialog,
)

from .._cli import as_cli


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
    """
    # Set up auto-handler if requested
    if auto_handle:
        try:
            await core_setup_auto_dialog_handler(tab, accept=accept)
            return {"success": True, "action": "auto_handler_enabled"}
        except Exception as e:
            return {"success": False, "error": "setup_failed", "message": str(e)}

    # If wait_timeout specified, wait for dialog
    if wait_timeout > 0:
        try:
            handled = await core_wait_for_dialog(
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
        handled = await core_handle_dialog(tab, accept=accept, prompt_text=prompt_text)
        if handled:
            return {"success": True, "action": "accepted" if accept else "dismissed"}
        return {
            "success": False,
            "error": "no_dialog",
            "message": "No dialog is currently showing",
        }
    except Exception as e:
        return {"success": False, "error": "unknown", "message": str(e)}


if __name__ == "__main__":
    page_handle_dialog.cli_main()
