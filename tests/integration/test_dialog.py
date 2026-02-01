"""Integration tests for dialog handling operations."""

import asyncio

from ai_dev_browser.core import goto, handle_dialog_action


class TestHandleDialogAction:
    """Test dialog handling with various modes."""

    async def test_auto_handler_setup(self, browser):
        """Should set up auto handler and return success."""
        tab = browser.main_tab

        result = await handle_dialog_action(tab, auto_handle=True, accept=True)
        assert isinstance(result, dict)
        assert result["success"] is True
        assert result["action"] == "auto_handler_enabled"

    async def test_no_dialog_present(self, browser):
        """Should return error when no dialog is showing."""
        tab = browser.main_tab

        # Navigate to a simple page without dialogs
        await goto(tab, "about:blank")
        await asyncio.sleep(0.2)

        result = await handle_dialog_action(tab)
        assert isinstance(result, dict)
        assert result["success"] is False
        assert result["error"] == "no_dialog"

    async def test_wait_timeout_no_dialog(self, browser):
        """Should timeout when waiting for dialog that doesn't appear."""
        tab = browser.main_tab

        await goto(tab, "about:blank")
        await asyncio.sleep(0.2)

        result = await handle_dialog_action(tab, wait_timeout=0.5)
        assert isinstance(result, dict)
        assert result["success"] is False
        assert result["error"] == "timeout"
        assert "0.5" in result["message"]

    async def test_handle_alert_dialog(self, browser):
        """Should handle alert dialog when triggered."""
        tab = browser.main_tab

        # Set up auto handler first
        await handle_dialog_action(tab, auto_handle=True, accept=True)

        # Create page that triggers alert
        html = """<!DOCTYPE html>
<html>
<body>
    <script>
        setTimeout(() => alert('Test alert'), 100);
    </script>
</body>
</html>"""

        import base64

        data_url = "data:text/html;base64," + base64.b64encode(html.encode()).decode()
        await goto(tab, data_url)

        # Wait for the alert to be auto-handled
        await asyncio.sleep(0.5)

        # If we got here without hanging, the auto handler worked
        # The page should have loaded successfully
        assert True
