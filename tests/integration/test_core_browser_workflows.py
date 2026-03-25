"""Core browser workflows: page operations, element interaction, state management.

Covers all non-lifecycle, non-AI-discovery workflows:
- Navigation: goto, back/forward, reload, wait, error recovery
- Page content: screenshot, HTML, JS eval, scroll
- Element interaction: forms, mouse, dynamic content, keyboard
- Dialog handling: alert, confirm (accept/reject), dialog+form combos
- Window management: resize, state, focus emulation
- Tabs: create, switch, close, multi-tab isolation
- Cookies: save, load, list
- Storage: localStorage set/get/clear
- CDP: raw command, download path

For browser lifecycle (start/stop/reuse/connect), see test_browser_lifecycle.py.
For AI-style find-and-interact workflows, see test_find_and_interact_workflows.py.
"""

import asyncio
import base64
import json
import tempfile
from pathlib import Path

from ai_dev_browser.core import (
    click_by_text,
    close_tab,
    find,
    focus_window,
    get_page_html,
    get_page_info,
    goto,
    handle_dialog_action,
    js_exec,
    list_cookies,
    list_tabs,
    load_cookies,
    mouse_click,
    mouse_drag,
    mouse_move,
    new_tab,
    reload,
    resize_window,
    save_cookies,
    screenshot,
    scroll,
    send_cdp_command,
    set_focus_emulation,
    set_window_state,
    switch_tab,
    type_by_ref,
    wait_for_load,
)
from ai_dev_browser.core import human
from ai_dev_browser.core.dialog import _setup_auto_dialog_handler
from ai_dev_browser.core.elements import (
    _click,
    _get_element_text,
    _type_text,
    _wait_for_element,
)
from ai_dev_browser.core.navigation import _back, _forward


def make_data_url(html: str) -> str:
    """Convert HTML to data URL."""
    return "data:text/html;base64," + base64.b64encode(html.encode()).decode()


async def eval_json(tab, js_expr):
    """Evaluate JS and return parsed JSON result."""
    result = await tab.evaluate(f"JSON.stringify({js_expr})")
    if result is None or result == "null":
        return None
    return json.loads(result)


# =============================================================================
# Navigation
# =============================================================================


class TestNavigationWorkflow:
    """Multi-page navigation: goto → interact → navigate → verify."""

    async def test_navigation_history(self, browser):
        """Navigate between pages using back/forward."""
        tab = browser.main_tab

        page1 = make_data_url("<html><body><h1>Page 1</h1></body></html>")
        page2 = make_data_url("<html><body><h1>Page 2</h1></body></html>")

        await goto(tab, page1)
        await asyncio.sleep(0.2)
        content = await tab.evaluate("document.body.innerText")
        assert "Page 1" in content

        await goto(tab, page2)
        await asyncio.sleep(0.2)

        await _back(tab)
        await asyncio.sleep(0.2)
        content = await tab.evaluate("document.body.innerText")
        assert "Page 1" in content

        await _forward(tab)
        await asyncio.sleep(0.2)
        content = await tab.evaluate("document.body.innerText")
        assert "Page 2" in content

    async def test_reload_workflow(self, browser):
        """Reload page and verify reload occurred."""
        tab = browser.main_tab

        html = make_data_url("""<!DOCTYPE html><html><body>
            <script>window.loadTime = Date.now();</script>
        </body></html>""")

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)
        load_time1 = await tab.evaluate("window.loadTime")

        await reload(tab)
        await asyncio.sleep(0.3)
        load_time2 = await tab.evaluate("window.loadTime")
        assert load_time2 > load_time1

    async def test_wait_for_page_load(self, browser):
        """Navigate and explicitly wait for page load."""
        tab = browser.main_tab

        html = make_data_url("""<!DOCTYPE html><html><body>
            <script>setTimeout(() => { window.loadComplete = true; }, 100);</script>
        </body></html>""")

        await tab.get(html)
        ready = await wait_for_load(tab, timeout=5)
        assert ready is True
        state = await tab.evaluate("document.readyState")
        assert state == "complete"

    async def test_recover_from_bad_navigation(self, browser):
        """Navigate to non-existent page, then recover."""
        tab = browser.main_tab

        await goto(tab, "http://localhost:1/nonexistent")
        await asyncio.sleep(0.5)
        await get_page_info(tab)

        good_html = make_data_url("<html><body><h1>Recovered!</h1></body></html>")
        await goto(tab, good_html)
        await asyncio.sleep(0.3)
        content = await tab.evaluate("document.body.innerText")
        assert "Recovered!" in content

    async def test_navigate_reload_navigate(self, browser):
        """Navigate → reload → navigate to different page."""
        tab = browser.main_tab

        html1 = make_data_url("<html><body>First</body></html>")
        await goto(tab, html1)
        await asyncio.sleep(0.3)

        await reload(tab)
        await asyncio.sleep(0.3)

        html2 = make_data_url("<html><body>Second</body></html>")
        await goto(tab, html2)
        await asyncio.sleep(0.3)
        content = await tab.evaluate("document.body.innerText")
        assert "Second" in content


# =============================================================================
# Page content & screenshots
# =============================================================================


class TestPageOperationsWorkflow:
    """Page capture: screenshot, HTML, info, scroll."""

    async def test_page_capture_workflow(self, browser):
        """Capture page state: screenshot, HTML, title."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><head><title>Test Page</title></head>
<body><h1 id="title">Hello World</h1><p id="content">Test content.</p></body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "screenshot.png"
            result = await screenshot(tab, path=str(path))
            assert Path(result["path"]).exists()

        html_result = await get_page_html(tab)
        assert "Hello World" in html_result.get("html", "")

        title = await tab.evaluate("document.title")
        assert "Test Page" in (title or "")

        text_result = await _get_element_text(tab, selector="#content")
        assert "content" in text_result.get("text", "").lower()

    async def test_scroll_workflow(self, browser):
        """Scroll through long page: down → bottom → top."""
        tab = browser.main_tab

        html = """<!DOCTYPE html><html><body style="height:3000px;">
            <div id="top">Top</div>
            <div id="bottom" style="position:absolute;bottom:0;">Bottom</div>
        </body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        await scroll(tab, direction="down", amount=500)
        await asyncio.sleep(0.1)
        assert await tab.evaluate("window.scrollY") > 0

        await scroll(tab, to_bottom=True)
        await asyncio.sleep(0.1)
        at_bottom = await tab.evaluate(
            "window.scrollY + window.innerHeight >= document.body.scrollHeight - 10"
        )
        assert at_bottom is True

        await scroll(tab, to_top=True)
        await asyncio.sleep(0.1)
        assert await tab.evaluate("window.scrollY") == 0

    async def test_scroll_read_then_interact(self, browser):
        """Scroll to read hidden info, scroll back, interact."""
        tab = browser.main_tab

        html = """<!DOCTYPE html><html><body style="height:3000px;">
            <button id="top-btn" onclick="window.topClicked=true">Top Action</button>
            <div style="height:2000px;">Spacer</div>
            <div id="bottom-info">Secret code: 42</div>
            <script>window.topClicked = false;</script>
        </body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        await scroll(tab, to_bottom=True)
        await asyncio.sleep(0.3)
        info = await tab.evaluate("document.getElementById('bottom-info').textContent")
        assert "42" in info

        await scroll(tab, to_top=True)
        await asyncio.sleep(0.3)
        await click_by_text(tab, text="Top Action")
        assert await tab.evaluate("window.topClicked") is True

    async def test_screenshot_different_pages(self, browser):
        """Screenshots of different pages should produce different files."""
        tab = browser.main_tab

        with tempfile.TemporaryDirectory() as tmpdir:
            await tab.get(
                make_data_url("<html><body style='background:red;'>Red</body></html>")
            )
            await asyncio.sleep(0.3)
            r1 = await screenshot(tab, path=str(Path(tmpdir) / "red.png"))

            await tab.get(
                make_data_url("<html><body style='background:blue;'>Blue</body></html>")
            )
            await asyncio.sleep(0.3)
            r2 = await screenshot(tab, path=str(Path(tmpdir) / "blue.png"))

            assert r1["size"] > 0 and r2["size"] > 0
            assert Path(r1["path"]).read_bytes() != Path(r2["path"]).read_bytes()

    async def test_full_page_screenshot(self, browser):
        """Full-page screenshot is taller than viewport screenshot."""
        tab = browser.main_tab

        html = make_data_url(
            "<html><body style='height:3000px;'><h1>Tall</h1></body></html>"
        )
        await tab.get(html)
        await asyncio.sleep(0.3)

        with tempfile.TemporaryDirectory() as tmpdir:
            r1 = await screenshot(
                tab, path=str(Path(tmpdir) / "vp.png"), full_page=False
            )
            r2 = await screenshot(
                tab, path=str(Path(tmpdir) / "full.png"), full_page=True
            )
            assert r2["height"] > r1["height"] or r2["size"] > r1["size"]

    async def test_eval_js_workflow(self, browser):
        """Execute JavaScript and get results."""
        tab = browser.main_tab

        html = make_data_url("""<!DOCTYPE html><html><body><script>
            window.data = {users: [{name: 'Alice'}, {name: 'Bob'}], config: {theme: 'dark'}};
        </script></body></html>""")

        await tab.get(html)
        await asyncio.sleep(0.2)

        assert (await js_exec(tab, "1 + 1")).get("result") == 2
        assert (await js_exec(tab, "window.data.users.length")).get("result") == 2
        assert (await js_exec(tab, "document.body.tagName")).get("result") == "BODY"


# =============================================================================
# Element interaction: forms, mouse, keyboard, dynamic content
# =============================================================================


class TestFormWorkflow:
    """Form interaction: navigate → fill fields → submit → verify."""

    async def test_complete_form_submission(self, browser):
        """Fill a multi-field form and submit."""
        tab = browser.main_tab

        html = """<!DOCTYPE html><html><body>
            <form><input id="name" type="text" placeholder="Name">
            <input id="email" type="email" placeholder="Email">
            <textarea id="message" placeholder="Message"></textarea>
            <select id="category"><option value="">Select</option><option value="bug">Bug</option>
            <option value="feature">Feature</option></select>
            <button id="submit" type="button" onclick="submitForm()">Submit</button></form>
            <script>window.submitted = null;
            function submitForm() { window.submitted = {
                name: document.getElementById('name').value,
                email: document.getElementById('email').value,
                message: document.getElementById('message').value,
                category: document.getElementById('category').value}; }</script>
        </body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        await _click(tab, selector="#name")
        await _type_text(tab, "John Doe", selector="#name")
        await _click(tab, selector="#email")
        await _type_text(tab, "john@example.com", selector="#email")
        await _click(tab, selector="#message")
        await _type_text(tab, "Test message.", selector="#message")
        await tab.evaluate("document.getElementById('category').value = 'feature'")
        await _click(tab, selector="#submit")
        await asyncio.sleep(0.1)

        submitted = await eval_json(tab, "window.submitted")
        assert submitted["name"] == "John Doe"
        assert submitted["email"] == "john@example.com"
        assert submitted["category"] == "feature"

    async def test_form_clear_and_retype(self, browser):
        """Clear existing values and retype."""
        tab = browser.main_tab

        html = make_data_url(
            '<html><body><input id="input" type="text" value="initial"></body></html>'
        )
        await tab.get(html)
        await asyncio.sleep(0.2)

        await _click(tab, selector="#input")
        await _type_text(tab, "new value", selector="#input", clear=True)
        assert (
            await tab.evaluate("document.getElementById('input').value") == "new value"
        )

    async def test_dynamic_form_with_validation(self, browser):
        """Form with dynamic validation feedback."""
        tab = browser.main_tab

        html = """<!DOCTYPE html><html><body>
            <input id="email" type="text" placeholder="Email">
            <button id="validate" onclick="validate()">Validate</button>
            <script>function validate() {
                window.isValid = document.getElementById('email').value.includes('@');
            }</script></body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        await _type_text(tab, "notanemail", selector="#email")
        await _click(tab, selector="#validate")
        assert await tab.evaluate("window.isValid") is False

        await _type_text(tab, "valid@email.com", selector="#email", clear=True)
        await _click(tab, selector="#validate")
        assert await tab.evaluate("window.isValid") is True

    async def test_multi_field_form_via_refs(self, browser):
        """Fill multiple fields using find + type_by_ref + click_by_text."""
        tab = browser.main_tab

        html = """<!DOCTYPE html><html><body>
            <form><input id="f1" type="text" placeholder="First">
            <input id="f2" type="text" placeholder="Second">
            <input id="f3" type="text" placeholder="Third">
            <button type="button" onclick="window.formResult = {
                f1: document.getElementById('f1').value,
                f2: document.getElementById('f2').value,
                f3: document.getElementById('f3').value}">Submit</button></form>
        </body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        result = await find(tab)
        fields = [el for el in result["elements"] if el.get("role") == "textbox"]
        assert len(fields) >= 3

        await type_by_ref(tab, ref=fields[0]["ref"], text="val1")
        await type_by_ref(tab, ref=fields[1]["ref"], text="val2")
        await type_by_ref(tab, ref=fields[2]["ref"], text="val3")
        await click_by_text(tab, text="Submit")
        await asyncio.sleep(0.1)

        form_result = await eval_json(tab, "window.formResult")
        assert form_result == {"f1": "val1", "f2": "val2", "f3": "val3"}


class TestMouseWorkflow:
    """Mouse operations: move → click → drag → verify."""

    async def test_mouse_move_and_click_sequence(self, browser):
        """Move mouse, click, verify trusted events."""
        tab = browser.main_tab

        html = """<!DOCTYPE html><html><body>
            <div id="target" style="width:200px;height:200px;background:#ccc;position:absolute;left:50px;top:50px;">
            Click me</div><script>
            window.events = [];
            document.getElementById('target').addEventListener('click', (e) => {
                window.events.push({type:'click', x:e.clientX, y:e.clientY, trusted:e.isTrusted});
            });
            document.addEventListener('mousemove', (e) => { window.lastMove = {x:e.clientX, y:e.clientY}; });
            </script></body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        await mouse_move(tab, 150, 150)
        last_move = await eval_json(tab, "window.lastMove")
        assert abs(last_move["x"] - 150) <= 2
        assert abs(last_move["y"] - 150) <= 2

        await mouse_click(tab, 150, 150)
        events = await eval_json(tab, "window.events")
        assert len(events) >= 1
        assert events[-1]["trusted"] is True
        assert human.get_last_mouse_pos(tab) == (150, 150)

    async def test_mouse_drag_operation(self, browser):
        """Drag element from one position to another."""
        tab = browser.main_tab

        html = make_data_url("""<html><body>
            <div id="draggable" draggable="true" style="width:50px;height:50px;background:blue;position:absolute;">
            </div></body></html>""")

        await tab.get(html)
        await asyncio.sleep(0.2)
        await mouse_drag(tab, from_x=25, from_y=25, to_x=200, to_y=200)
        assert human.get_last_mouse_pos(tab) == (200, 200)

    async def test_rapid_mouse_operations(self, browser):
        """Many mouse operations maintain consistent position tracking."""
        tab = browser.main_tab

        html = make_data_url("""<html><body>
            <script>window.moves = 0; document.addEventListener('mousemove', () => window.moves++);</script>
        </body></html>""")

        await tab.get(html)
        await asyncio.sleep(0.2)

        for i in range(20):
            x = 100 + (i % 5) * 50
            y = 100 + (i // 5) * 50
            await mouse_move(tab, x, y)
            assert human.get_last_mouse_pos(tab) == (x, y)

        assert await tab.evaluate("window.moves") >= 20


class TestDialogWorkflow:
    """Dialog handling: alert, confirm accept/reject, dialog+form combos."""

    async def test_alert_dialog_handling(self, browser):
        """Handle alert dialog automatically."""
        tab = browser.main_tab

        html = """<!DOCTYPE html><html><body>
            <button id="alert-btn" onclick="showAlert()">Alert</button>
            <script>window.alertShown = false;
            function showAlert() { window.alertShown = true; alert('Test'); window.alertDismissed = true; }
            </script></body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)
        await _setup_auto_dialog_handler(tab, accept=True)
        await _click(tab, selector="#alert-btn")
        await asyncio.sleep(0.3)

        assert await tab.evaluate("window.alertShown") is True
        assert await tab.evaluate("window.alertDismissed") is True

    async def test_no_dialog_returns_appropriate_result(self, browser):
        """Handling when no dialog present."""
        tab = browser.main_tab
        await tab.get(make_data_url("<html><body>No dialogs</body></html>"))
        await asyncio.sleep(0.2)
        result = await handle_dialog_action(tab, accept=True, wait_timeout=0)
        assert (
            result.get("handled") is False
            or "error" in result
            or result.get("no_dialog")
        )

    async def test_confirm_dialog_accept(self, browser):
        """Form → confirm dialog → auto-accept → verify submission."""
        tab = browser.main_tab

        html = """<!DOCTYPE html><html><body>
            <input id="name" type="text" placeholder="Name">
            <button id="submit" onclick="submitWithConfirm()">Submit</button>
            <div id="result"></div>
            <script>window.submitted = false;
            function submitWithConfirm() {
                if (confirm('Sure?')) { window.submitted = true;
                    document.getElementById('result').textContent = 'Submitted: ' +
                    document.getElementById('name').value;
                } else { document.getElementById('result').textContent = 'Cancelled'; }
            }</script></body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)
        await _type_text(tab, "Alice", selector="#name")
        await _setup_auto_dialog_handler(tab, accept=True)
        await _click(tab, selector="#submit")
        await asyncio.sleep(0.3)

        assert await tab.evaluate("window.submitted") is True
        assert "Submitted: Alice" in await tab.evaluate(
            "document.getElementById('result').textContent"
        )

    async def test_confirm_dialog_reject(self, browser):
        """Auto-dismiss confirm dialog cancels action."""
        tab = browser.main_tab

        html = """<!DOCTYPE html><html><body>
            <button id="btn" onclick="doAction()">Action</button><div id="status">idle</div>
            <script>function doAction() {
                document.getElementById('status').textContent = confirm('Proceed?') ? 'confirmed' : 'rejected';
            }</script></body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)
        await _setup_auto_dialog_handler(tab, accept=False)
        await _click(tab, selector="#btn")
        await asyncio.sleep(0.3)
        assert (
            await tab.evaluate("document.getElementById('status').textContent")
            == "rejected"
        )


class TestDynamicContentWorkflow:
    """Dynamic content: wait for elements, interact with loaded content."""

    async def test_wait_and_interact(self, browser):
        """Wait for dynamically loaded element then click."""
        tab = browser.main_tab

        html = """<!DOCTYPE html><html><body><div id="container"></div>
            <script>window.clicked = false;
            setTimeout(() => { const btn = document.createElement('button');
                btn.id = 'delayed-btn'; btn.textContent = 'Click Me';
                btn.onclick = () => { window.clicked = true; };
                document.getElementById('container').appendChild(btn); }, 300);
            </script></body></html>"""

        await tab.get(make_data_url(html))
        result = await _wait_for_element(tab, selector="#delayed-btn", timeout=5)
        assert result.get("found") is True
        await _click(tab, selector="#delayed-btn")
        assert await tab.evaluate("window.clicked") is True

    async def test_content_update_after_action(self, browser):
        """Click to load content → wait → verify."""
        tab = browser.main_tab

        html = """<!DOCTYPE html><html><body>
            <button id="load-btn" onclick="loadContent()">Load</button><div id="content"></div>
            <script>function loadContent() {
                document.getElementById('content').innerHTML = '<p id=\"loaded\">Loaded!</p>';
            }</script></body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)
        await _click(tab, selector="#load-btn")
        result = await _wait_for_element(tab, selector="#loaded", timeout=2)
        assert result.get("found") is True
        text = await _get_element_text(tab, selector="#loaded")
        assert "loaded" in text.get("text", "").lower()


# =============================================================================
# Window management
# =============================================================================


class TestWindowWorkflow:
    """Window management: resize, state, focus."""

    async def test_resize_and_verify(self, browser):
        """Resize window and verify dimensions."""
        tab = browser.main_tab
        await tab.get(make_data_url("<html><body></body></html>"))
        await asyncio.sleep(0.2)

        result = await resize_window(tab, width=800, height=600)
        assert result["width"] == 800

        await asyncio.sleep(0.2)
        inner_width = await tab.evaluate("window.innerWidth")
        assert abs(inner_width - 800) < 50

    async def test_focus_window(self, browser):
        """Focus window."""
        tab = browser.main_tab
        assert (await focus_window(tab)).get("focused") is True

    async def test_window_state_transitions(self, browser):
        """Change window state: normal → maximized → normal."""
        tab = browser.main_tab
        assert (await set_window_state(tab, state="normal"))["state"] == "normal"
        assert (await set_window_state(tab, state="maximized"))["state"] == "maximized"
        assert (await set_window_state(tab, state="normal"))["state"] == "normal"

    async def test_focus_emulation(self, browser):
        """Enable/disable focus emulation."""
        tab = browser.main_tab
        assert (await set_focus_emulation(tab, enabled=True))["enabled"] is True
        assert await tab.evaluate("document.hasFocus()") is True
        assert (await set_focus_emulation(tab, enabled=False))["enabled"] is False


# =============================================================================
# Tabs
# =============================================================================


class TestTabWorkflow:
    """Tab lifecycle: create → navigate → switch → close."""

    async def test_create_navigate_switch_close(self, browser):
        """Full tab lifecycle."""
        tab1 = browser.main_tab
        await tab1.get(make_data_url("<html><body><h1>Tab 1</h1></body></html>"))
        await asyncio.sleep(0.3)

        result = await new_tab(browser)
        tab2 = result["tab"]
        await tab2.get(make_data_url("<html><body><h1>Tab 2</h1></body></html>"))
        await asyncio.sleep(0.3)
        assert "Tab 2" in await tab2.evaluate("document.body.innerText")

        tabs_result = await list_tabs(browser)
        assert tabs_result["count"] >= 2

        await switch_tab(browser, tab_id=0)
        await close_tab(browser, tab=tab2)
        assert (await list_tabs(browser))["count"] >= 1

    async def test_multi_tab_state_isolation(self, browser):
        """JS state in one tab does not leak to another."""
        tab1 = browser.main_tab
        html = make_data_url(
            "<html><body><script>window.tabState = 'unset';</script></body></html>"
        )

        await tab1.get(html)
        await asyncio.sleep(0.2)
        await tab1.evaluate("window.tabState = 'tab1_value'")

        result = await new_tab(browser)
        tab2 = result["tab"]
        await tab2.get(html)
        await asyncio.sleep(0.2)
        await tab2.evaluate("window.tabState = 'tab2_value'")

        assert await tab1.evaluate("window.tabState") == "tab1_value"
        assert await tab2.evaluate("window.tabState") == "tab2_value"
        await close_tab(browser, tab=tab2)

    async def test_switch_back_preserves_state(self, browser):
        """Open tab2, do work, switch back to tab1 — state preserved."""
        tab1 = browser.main_tab
        await tab1.get(
            make_data_url("<html><body><div id='m'>Original</div></body></html>")
        )
        await asyncio.sleep(0.2)
        await tab1.evaluate("document.getElementById('m').textContent = 'Modified'")

        result = await new_tab(browser)
        tab2 = result["tab"]
        await tab2.get(make_data_url("<html><body>Tab2</body></html>"))
        await asyncio.sleep(0.2)

        await switch_tab(browser, tab_id=0)
        assert (
            await tab1.evaluate("document.getElementById('m').textContent")
            == "Modified"
        )
        await close_tab(browser, tab=tab2)


# =============================================================================
# Cookies
# =============================================================================


class TestCookieWorkflow:
    """Cookie save → load → list."""

    async def test_save_and_load_cookies(self, browser):
        """Save cookies to file → load back."""
        tab = browser.main_tab

        with tempfile.NamedTemporaryFile(suffix=".dat", delete=False) as f:
            cookie_path = f.name

        try:
            save_result = await save_cookies(tab, path=cookie_path)
            assert save_result.get("saved") is True
            assert Path(cookie_path).exists()

            load_result = await load_cookies(tab, path=cookie_path)
            assert load_result.get("loaded") is True
        finally:
            Path(cookie_path).unlink(missing_ok=True)

    async def test_list_cookies_structure(self, browser):
        """list_cookies returns proper structure."""
        tab = browser.main_tab
        result = await list_cookies(tab)
        assert isinstance(result["cookies"], list)
        assert isinstance(result["count"], int)


# =============================================================================
# Storage & Downloads
# =============================================================================


class TestStorageWorkflow:
    """LocalStorage: set → reload → verify → clear."""

    async def test_set_reload_verify_clear(self, browser):
        """Set localStorage, reload, verify persistence, clear."""
        tab = browser.main_tab
        await goto(tab, "https://example.com")
        await asyncio.sleep(0.5)

        await tab.evaluate("localStorage.setItem('testKey', 'testValue123')")
        assert await tab.evaluate("localStorage.getItem('testKey')") == "testValue123"

        await tab.reload()
        await asyncio.sleep(0.5)
        assert await tab.evaluate("localStorage.getItem('testKey')") == "testValue123"

        await tab.evaluate("localStorage.removeItem('testKey')")
        assert await tab.evaluate("localStorage.getItem('testKey')") is None

    async def test_batch_local_storage(self, browser):
        """Set multiple localStorage items, verify all."""
        tab = browser.main_tab
        await goto(tab, "https://example.com")
        await asyncio.sleep(0.5)

        await tab.evaluate("""
            localStorage.setItem('k1', 'v1');
            localStorage.setItem('k2', 'v2');
            localStorage.setItem('k3', 'v3');
        """)

        assert await tab.evaluate("localStorage.getItem('k1')") == "v1"
        assert await tab.evaluate("localStorage.getItem('k2')") == "v2"
        assert await tab.evaluate("localStorage.getItem('k3')") == "v3"
        await tab.evaluate("localStorage.clear()")

    async def test_storage_via_cdp_api(self, browser):
        """Set/get localStorage using the CDP-based API."""
        tab = browser.main_tab
        await goto(tab, "https://example.com")
        await asyncio.sleep(0.5)

        from ai_dev_browser.core import get_local_storage, set_local_storage

        await set_local_storage(tab, key="cdp_key", value="cdp_value")
        result = await get_local_storage(tab, key="cdp_key")
        assert result.get("value") == "cdp_value"
        await tab.evaluate("localStorage.clear()")


class TestDownloadAndCdpWorkflow:
    """Download path, raw CDP commands."""

    async def test_set_download_path(self, browser):
        """Set download path."""
        tab = browser.main_tab
        with tempfile.TemporaryDirectory() as tmpdir:
            from ai_dev_browser.core import set_download_path

            result = await set_download_path(tab, path=tmpdir)
            assert Path(result["path"]).exists()

    async def test_cdp_get_version(self, browser):
        """Send raw CDP Browser.getVersion."""
        tab = browser.main_tab
        result = await send_cdp_command(tab, method="Browser.getVersion")
        assert "result" in result

    async def test_cdp_evaluate_expression(self, browser):
        """Send raw CDP Runtime.evaluate."""
        tab = browser.main_tab
        await tab.get(make_data_url("<html><body>CDP</body></html>"))
        await asyncio.sleep(0.2)
        result = await send_cdp_command(
            tab, method="Runtime.evaluate", params='{"expression": "1 + 2 + 3"}'
        )
        assert "result" in result
