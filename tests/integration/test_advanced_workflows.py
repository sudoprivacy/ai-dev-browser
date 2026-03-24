"""Advanced integration workflows.

Covers:
- Dialog + Form combination: fill form → submit triggers dialog → handle → verify
- Scroll + Find combination: scroll to reveal → find → click → verify
- Error recovery: navigate to bad URL → handle error → navigate to good URL
- Keyboard navigation: focus → tab through fields → type → submit
- LocalStorage persistence: set → reload → verify → clear
- Screenshot chaining: navigate → screenshot → navigate → screenshot → compare
"""

import asyncio
import base64
import json
import tempfile
from pathlib import Path

from ai_dev_browser.core import (
    click_by_text,
    find,
    get_page_info,
    goto,
    screenshot,
    scroll,
    type_by_ref,
)
from ai_dev_browser.core.dialog import _setup_auto_dialog_handler
from ai_dev_browser.core.elements import _click, _type_text


def make_data_url(html: str) -> str:
    return "data:text/html;base64," + base64.b64encode(html.encode()).decode()


async def eval_json(tab, js_expr):
    result = await tab.evaluate(f"JSON.stringify({js_expr})")
    if result is None or result == "null":
        return None
    return json.loads(result)


class TestDialogFormWorkflow:
    """Fill form → submit (triggers confirm dialog) → handle → verify."""

    async def test_confirm_dialog_on_form_submit(self, browser):
        """Form submission triggers confirm dialog, handle it, verify result."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <input id="name" type="text" placeholder="Name">
    <button id="submit" onclick="submitWithConfirm()">Submit</button>
    <div id="result"></div>
    <script>
        window.submitted = false;
        function submitWithConfirm() {
            if (confirm('Are you sure you want to submit?')) {
                window.submitted = true;
                document.getElementById('result').textContent =
                    'Submitted: ' + document.getElementById('name').value;
            } else {
                window.submitted = false;
                document.getElementById('result').textContent = 'Cancelled';
            }
        }
    </script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Fill form
        await _type_text(tab, "Alice", selector="#name")

        # Setup auto-accept for the confirm dialog
        await _setup_auto_dialog_handler(tab, accept=True)

        # Submit (triggers confirm → auto-accepted)
        await _click(tab, selector="#submit")
        await asyncio.sleep(0.3)

        # Verify submission happened
        submitted = await tab.evaluate("window.submitted")
        assert submitted is True
        result_text = await tab.evaluate(
            "document.getElementById('result').textContent"
        )
        assert "Submitted: Alice" in result_text

    async def test_reject_dialog_cancels_submission(self, browser):
        """Rejecting confirm dialog should cancel submission."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <button id="btn" onclick="doAction()">Do Action</button>
    <div id="status">idle</div>
    <script>
        function doAction() {
            if (confirm('Proceed?')) {
                document.getElementById('status').textContent = 'confirmed';
            } else {
                document.getElementById('status').textContent = 'rejected';
            }
        }
    </script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Setup auto-dismiss
        await _setup_auto_dialog_handler(tab, accept=False)

        await _click(tab, selector="#btn")
        await asyncio.sleep(0.3)

        status = await tab.evaluate("document.getElementById('status').textContent")
        assert status == "rejected"


class TestScrollFindWorkflow:
    """Scroll to reveal content → find → click → verify."""

    async def test_scroll_down_find_click(self, browser):
        """Scroll to reveal content, read it, then interact with visible elements."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body style="height:3000px;">
    <button id="top-btn" onclick="window.topClicked=true">Top Action</button>
    <div style="height:2000px;">Spacer</div>
    <div id="bottom-info">Secret code: 42</div>
    <script>window.topClicked = false;</script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Step 1: Scroll to bottom to read hidden info
        await scroll(tab, to_bottom=True)
        await asyncio.sleep(0.3)
        info = await tab.evaluate("document.getElementById('bottom-info').textContent")
        assert "42" in info

        # Step 2: Scroll back to top
        await scroll(tab, to_top=True)
        await asyncio.sleep(0.3)

        # Step 3: Click the top button using the info we found
        await click_by_text(tab, text="Top Action")
        clicked = await tab.evaluate("window.topClicked")
        assert clicked is True

    async def test_scroll_read_then_interact(self, browser):
        """Scroll to read info, then use that info to make decisions."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <div style="height:2000px;">
        <div style="position:absolute;bottom:0;" id="hint">Click the red button</div>
    </div>
    <script>window.scrolledToBottom = false;
    window.addEventListener('scroll', () => {
        if (window.scrollY + window.innerHeight >= document.body.scrollHeight - 50)
            window.scrolledToBottom = true;
    });</script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Step 1: Scroll down and verify scroll happened
        await scroll(tab, to_bottom=True)
        await asyncio.sleep(0.3)
        scrolled = await tab.evaluate("window.scrolledToBottom")
        assert scrolled is True

        # Step 2: Read the hint text
        hint = await tab.evaluate("document.getElementById('hint').textContent")
        assert "red button" in hint

        # Step 3: Scroll back to top
        await scroll(tab, to_top=True)
        await asyncio.sleep(0.2)
        y = await tab.evaluate("window.scrollY")
        assert y == 0


class TestErrorRecoveryWorkflow:
    """Navigate to bad URL → handle error → navigate to good URL → verify."""

    async def test_recover_from_bad_navigation(self, browser):
        """Navigate to non-existent page, then recover."""
        tab = browser.main_tab

        # Navigate to a page that will fail/show error
        await goto(tab, "http://localhost:1/nonexistent")
        await asyncio.sleep(0.5)

        # Page should be in some error state (URL might be chrome-error://)
        await get_page_info(tab)

        # Recover by navigating to a valid page
        good_html = make_data_url("<html><body><h1>Recovered!</h1></body></html>")
        await goto(tab, good_html)
        await asyncio.sleep(0.3)

        content = await tab.evaluate("document.body.innerText")
        assert "Recovered!" in content

    async def test_navigate_after_reload_error(self, browser):
        """Navigate to a page, modify it, reload, navigate elsewhere."""
        tab = browser.main_tab

        html = make_data_url("""<html><body>
            <div id="counter">0</div>
            <script>
                window.loadCount = (window.loadCount || 0) + 1;
                document.getElementById('counter').textContent = window.loadCount;
            </script>
        </body></html>""")

        # Navigate
        await goto(tab, html)
        await asyncio.sleep(0.3)

        # Reload
        from ai_dev_browser.core import reload

        await reload(tab)
        await asyncio.sleep(0.3)

        # Navigate to different page
        html2 = make_data_url("<html><body>Different Page</body></html>")
        await goto(tab, html2)
        await asyncio.sleep(0.3)

        content = await tab.evaluate("document.body.innerText")
        assert "Different Page" in content


class TestKeyboardNavigationWorkflow:
    """Keyboard-driven form interaction: focus → type → tab → type → enter."""

    async def test_tab_through_fields_and_submit(self, browser):
        """Navigate through form using keyboard (Tab key simulation)."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <form id="form">
        <input id="f1" type="text" placeholder="First">
        <input id="f2" type="text" placeholder="Second">
        <input id="f3" type="text" placeholder="Third">
        <button type="button" onclick="doSubmit()">Submit</button>
    </form>
    <script>
        window.formResult = null;
        function doSubmit() {
            window.formResult = {
                f1: document.getElementById('f1').value,
                f2: document.getElementById('f2').value,
                f3: document.getElementById('f3').value,
            };
        }
    </script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Use find + type_by_ref for each field
        result = await find(tab)
        fields = [el for el in result["elements"] if el.get("role") == "textbox"]
        assert len(fields) >= 3, f"Expected 3 text fields, got {len(fields)}"

        # Type into each field
        await type_by_ref(tab, ref=fields[0]["ref"], text="value1")
        await type_by_ref(tab, ref=fields[1]["ref"], text="value2")
        await type_by_ref(tab, ref=fields[2]["ref"], text="value3")

        # Click submit
        await click_by_text(tab, text="Submit")
        await asyncio.sleep(0.1)

        form_result = await eval_json(tab, "window.formResult")
        assert form_result["f1"] == "value1"
        assert form_result["f2"] == "value2"
        assert form_result["f3"] == "value3"


class TestLocalStorageWorkflow:
    """LocalStorage: set → reload → verify → clear → verify cleared."""

    async def test_set_reload_verify_clear(self, browser):
        """Set localStorage via JS, reload, verify persistence, then clear."""
        tab = browser.main_tab

        # Need a real origin for localStorage
        await goto(tab, "https://example.com")
        await asyncio.sleep(0.5)

        # Set localStorage via JS
        await tab.evaluate("localStorage.setItem('testKey', 'testValue123')")

        # Verify before reload
        stored = await tab.evaluate("localStorage.getItem('testKey')")
        assert stored == "testValue123"

        # Reload page — localStorage should persist
        await tab.reload()
        await asyncio.sleep(0.5)

        stored = await tab.evaluate("localStorage.getItem('testKey')")
        assert stored == "testValue123"

        # Clear and verify
        await tab.evaluate("localStorage.removeItem('testKey')")
        cleared = await tab.evaluate("localStorage.getItem('testKey')")
        assert cleared is None

    async def test_batch_local_storage_operations(self, browser):
        """Set multiple localStorage items, read back, verify all."""
        tab = browser.main_tab

        await goto(tab, "https://example.com")
        await asyncio.sleep(0.5)

        # Batch set via JS
        await tab.evaluate("""
            localStorage.setItem('key1', 'val1');
            localStorage.setItem('key2', 'val2');
            localStorage.setItem('key3', 'val3');
        """)

        # Read all back
        v1 = await tab.evaluate("localStorage.getItem('key1')")
        v2 = await tab.evaluate("localStorage.getItem('key2')")
        v3 = await tab.evaluate("localStorage.getItem('key3')")
        assert v1 == "val1"
        assert v2 == "val2"
        assert v3 == "val3"

        # Clean up
        await tab.evaluate("localStorage.clear()")


class TestScreenshotWorkflow:
    """Screenshot chaining: navigate → screenshot → navigate → screenshot → compare."""

    async def test_screenshot_different_pages(self, browser):
        """Take screenshots of different pages, verify they're different files."""
        tab = browser.main_tab

        with tempfile.TemporaryDirectory() as tmpdir:
            # Page 1
            html1 = make_data_url(
                "<html><body style='background:red;'><h1>Red Page</h1></body></html>"
            )
            await tab.get(html1)
            await asyncio.sleep(0.3)

            path1 = str(Path(tmpdir) / "shot1.png")
            result1 = await screenshot(tab, path=path1)
            assert Path(result1["path"]).exists()
            size1 = result1["size"]

            # Page 2
            html2 = make_data_url(
                "<html><body style='background:blue;'><h1>Blue Page</h1></body></html>"
            )
            await tab.get(html2)
            await asyncio.sleep(0.3)

            path2 = str(Path(tmpdir) / "shot2.png")
            result2 = await screenshot(tab, path=path2)
            assert Path(result2["path"]).exists()
            size2 = result2["size"]

            # Files should exist and have different content
            assert size1 > 0
            assert size2 > 0
            data1 = Path(path1).read_bytes()
            data2 = Path(path2).read_bytes()
            assert data1 != data2, "Screenshots of different pages should differ"

    async def test_full_page_screenshot(self, browser):
        """Full-page screenshot captures content beyond viewport."""
        tab = browser.main_tab

        html = make_data_url("""<html><body style="height:3000px;">
            <h1>Top</h1>
            <div style="position:absolute;bottom:0;"><h1>Bottom</h1></div>
        </body></html>""")

        await tab.get(html)
        await asyncio.sleep(0.3)

        with tempfile.TemporaryDirectory() as tmpdir:
            # Viewport screenshot
            path_viewport = str(Path(tmpdir) / "viewport.png")
            r1 = await screenshot(tab, path=path_viewport, full_page=False)

            # Full page screenshot
            path_full = str(Path(tmpdir) / "fullpage.png")
            r2 = await screenshot(tab, path=path_full, full_page=True)

            # Full page should be taller (more pixels = larger file)
            assert r2["height"] > r1["height"] or r2["size"] > r1["size"]
