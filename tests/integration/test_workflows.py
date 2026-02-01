"""Integration tests using realistic workflow scenarios.

Each workflow tests multiple modules working together, mimicking real AI usage patterns.
"""

import asyncio
import base64
import json
import tempfile
from pathlib import Path

from ai_dev_browser.core import (
    back,
    click,
    click_ax_element,
    eval_js,
    focus_window,
    forward,
    get_accessibility_tree,
    get_element_text,
    get_page_html,
    get_page_info,
    get_snapshot,
    goto,
    handle_dialog_action,
    human,
    mouse_click,
    mouse_drag,
    mouse_move,
    new_tab,
    reload,
    resize_window,
    screenshot,
    scroll,
    setup_auto_dialog_handler,
    type_text,
    wait_for_element,
)


def make_data_url(html: str) -> str:
    """Convert HTML to data URL."""
    return "data:text/html;base64," + base64.b64encode(html.encode()).decode()


async def eval_json(tab, js_expr):
    """Evaluate JS and return parsed JSON result."""
    result = await tab.evaluate(f"JSON.stringify({js_expr})")
    if result is None or result == "null":
        return None
    return json.loads(result)


class TestFormWorkflow:
    """Form interaction: navigate → find fields → type → submit → verify.

    Covers: navigation, elements, type_text, click, wait_for_element, eval_js
    """

    async def test_complete_form_submission(self, browser):
        """Fill a multi-field form and submit."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <form id="form">
        <input id="name" type="text" placeholder="Name">
        <input id="email" type="email" placeholder="Email">
        <textarea id="message" placeholder="Message"></textarea>
        <select id="category">
            <option value="">Select...</option>
            <option value="bug">Bug Report</option>
            <option value="feature">Feature Request</option>
        </select>
        <button id="submit" type="button" onclick="submitForm()">Submit</button>
    </form>
    <div id="result"></div>
    <script>
        window.submitted = null;
        function submitForm() {
            window.submitted = {
                name: document.getElementById('name').value,
                email: document.getElementById('email').value,
                message: document.getElementById('message').value,
                category: document.getElementById('category').value,
                timestamp: Date.now()
            };
            document.getElementById('result').innerText = 'Submitted!';
        }
    </script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Fill form fields
        await click(tab, selector="#name")
        await type_text(tab, "John Doe", selector="#name")

        await click(tab, selector="#email")
        await type_text(tab, "john@example.com", selector="#email")

        await click(tab, selector="#message")
        await type_text(tab, "This is a test message.", selector="#message")

        # Select dropdown
        await click(tab, selector="#category")
        await tab.evaluate("document.getElementById('category').value = 'feature'")

        # Submit
        await click(tab, selector="#submit")
        await asyncio.sleep(0.1)

        # Verify submission
        submitted = await eval_json(tab, "window.submitted")
        assert submitted is not None
        assert submitted["name"] == "John Doe"
        assert submitted["email"] == "john@example.com"
        assert "test message" in submitted["message"]
        assert submitted["category"] == "feature"

    async def test_form_clear_and_retype(self, browser):
        """Clear existing values and retype."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <input id="input" type="text" value="initial value">
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Clear and type new value
        await click(tab, selector="#input")
        await type_text(tab, "new value", selector="#input", clear=True)

        value = await tab.evaluate("document.getElementById('input').value")
        assert value == "new value"

    async def test_dynamic_form_with_validation(self, browser):
        """Form with dynamic validation feedback."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <input id="email" type="text" placeholder="Email">
    <div id="error" style="color: red; display: none;">Invalid email</div>
    <button id="validate" onclick="validate()">Validate</button>
    <script>
        function validate() {
            const email = document.getElementById('email').value;
            const error = document.getElementById('error');
            const valid = email.includes('@');
            error.style.display = valid ? 'none' : 'block';
            window.isValid = valid;
        }
    </script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Type invalid email
        await type_text(tab, "notanemail", selector="#email")
        await click(tab, selector="#validate")
        is_valid = await tab.evaluate("window.isValid")
        assert is_valid is False

        # Clear and type valid email
        await type_text(tab, "valid@email.com", selector="#email", clear=True)
        await click(tab, selector="#validate")
        is_valid = await tab.evaluate("window.isValid")
        assert is_valid is True


class TestNavigationWorkflow:
    """Multi-page navigation: goto → interact → navigate → verify.

    Covers: goto, back, forward, reload, wait_for_url, get_page_info, tabs
    """

    async def test_navigation_history(self, browser):
        """Navigate between pages using back/forward."""
        tab = browser.main_tab

        page1 = make_data_url("<html><body><h1>Page 1</h1></body></html>")
        page2 = make_data_url("<html><body><h1>Page 2</h1></body></html>")

        # Navigate to page 1
        await goto(tab, page1)
        await asyncio.sleep(0.2)
        info1 = await get_page_info(tab)
        assert (
            "Page 1" in info1.get("title", "")
            or await tab.evaluate("document.body.innerText") == "Page 1"
        )

        # Navigate to page 2
        await goto(tab, page2)
        await asyncio.sleep(0.2)

        # Go back
        await back(tab)
        await asyncio.sleep(0.2)
        content = await tab.evaluate("document.body.innerText")
        assert "Page 1" in content

        # Go forward
        await forward(tab)
        await asyncio.sleep(0.2)
        content = await tab.evaluate("document.body.innerText")
        assert "Page 2" in content

    async def test_new_tab_creation(self, browser):
        """Create new tab and verify it works."""
        result = await new_tab(browser)
        tab = result.get("tab")
        assert tab is not None

        # Can execute JS in new tab
        result = await tab.evaluate("1 + 1")
        assert result == 2

    async def test_reload_workflow(self, browser):
        """Reload page and verify reload occurred."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <script>
        window.loadTime = Date.now();
    </script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)
        load_time1 = await tab.evaluate("window.loadTime")

        # Reload
        await reload(tab)
        await asyncio.sleep(0.3)
        load_time2 = await tab.evaluate("window.loadTime")

        # loadTime should be different after reload
        assert load_time2 > load_time1


class TestAccessibilityWorkflow:
    """Accessibility tree operations: snapshot → find → click → verify.

    Covers: get_snapshot, get_accessibility_tree, click_ax_element, wait_for_ax_element
    """

    async def test_ax_tree_navigation(self, browser):
        """Use accessibility tree to find and click elements."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <button id="action-btn">Click Me</button>
    <script>
        window.clicked = false;
        document.getElementById('action-btn').onclick = () => {
            window.clicked = true;
        };
    </script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Get accessibility tree
        result = await get_accessibility_tree(tab)
        assert "elements" in result
        elements = result["elements"]
        assert len(elements) > 0

        # Find button in snapshot
        snapshot = await get_snapshot(tab)
        button = None
        for el in snapshot:
            if el.get("role") == "button":
                button = el
                break

        assert button is not None, "Should find button in AX tree"
        assert button.get("ref") is not None, "Button should have ref"

        # Click using ax_element (by ref)
        result = await click_ax_element(tab, ref=button["ref"])
        assert result.get("clicked") is True

        clicked = await tab.evaluate("window.clicked")
        assert clicked is True

    async def test_ax_snapshot_element_types(self, browser):
        """Verify different element types appear in accessibility tree."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <h1>Heading</h1>
    <p>Paragraph text</p>
    <a href="#">Link</a>
    <button>Button</button>
    <input type="text" placeholder="Text input">
    <input type="checkbox" id="cb"><label for="cb">Checkbox</label>
    <select><option>Option 1</option></select>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        snapshot = await get_snapshot(tab)
        roles = {el.get("role") for el in snapshot if el.get("role")}

        # Should have various roles
        expected_roles = {"heading", "button", "link", "textbox"}
        found = expected_roles.intersection(roles)
        assert len(found) >= 3, f"Expected common roles, found: {roles}"


class TestMouseWorkflow:
    """Mouse operations: move → click → drag → verify positions.

    Covers: mouse_move, mouse_click, mouse_drag, human module
    """

    async def test_mouse_move_and_click_sequence(self, browser):
        """Move mouse to positions, click, verify events."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <div id="target" style="width:200px;height:200px;background:#ccc;position:absolute;left:50px;top:50px;">
        Click me
    </div>
    <script>
        window.events = [];
        document.getElementById('target').addEventListener('click', (e) => {
            window.events.push({type:'click', x:e.clientX, y:e.clientY, trusted:e.isTrusted});
        });
        document.addEventListener('mousemove', (e) => {
            window.lastMove = {x:e.clientX, y:e.clientY};
        });
    </script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Move to center of target (50+100=150, 50+100=150)
        await mouse_move(tab, 150, 150)
        last_move = await eval_json(tab, "window.lastMove")
        assert abs(last_move["x"] - 150) <= 2
        assert abs(last_move["y"] - 150) <= 2

        # Click
        await mouse_click(tab, 150, 150)
        events = await eval_json(tab, "window.events")
        assert len(events) >= 1
        assert events[-1]["trusted"] is True

        # Verify position tracking
        pos = human.get_last_mouse_pos(tab)
        assert pos == (150, 150)

    async def test_mouse_drag_operation(self, browser):
        """Drag element from one position to another."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <div id="draggable" draggable="true" style="width:50px;height:50px;background:blue;position:absolute;left:0;top:0;">
    </div>
    <div id="dropzone" style="width:200px;height:200px;background:#eee;position:absolute;left:100px;top:100px;">
        Drop here
    </div>
    <script>
        window.dragEvents = [];
        const el = document.getElementById('draggable');
        el.addEventListener('dragstart', (e) => window.dragEvents.push('start'));
        el.addEventListener('dragend', (e) => window.dragEvents.push('end'));
        document.getElementById('dropzone').addEventListener('dragover', (e) => {
            e.preventDefault();
            window.dragEvents.push('over');
        });
        document.getElementById('dropzone').addEventListener('drop', (e) => {
            e.preventDefault();
            window.dragEvents.push('drop');
        });
    </script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Perform drag
        await mouse_drag(tab, from_x=25, from_y=25, to_x=200, to_y=200)

        # Position should be at end
        pos = human.get_last_mouse_pos(tab)
        assert pos == (200, 200)

    async def test_rapid_mouse_operations(self, browser):
        """Many mouse operations in sequence should maintain consistency."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <script>window.moves = 0; document.addEventListener('mousemove', () => window.moves++);</script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Rapid moves in a pattern
        for i in range(20):
            x = 100 + (i % 5) * 50
            y = 100 + (i // 5) * 50
            await mouse_move(tab, x, y)
            pos = human.get_last_mouse_pos(tab)
            assert pos == (x, y), f"Position mismatch at iteration {i}"

        moves = await tab.evaluate("window.moves")
        assert moves >= 20


class TestDialogWorkflow:
    """Dialog handling: setup handler → trigger → verify.

    Covers: setup_auto_dialog_handler, handle_dialog_action
    """

    async def test_alert_dialog_handling(self, browser):
        """Handle alert dialog automatically."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <button id="alert-btn" onclick="showAlert()">Show Alert</button>
    <script>
        window.alertShown = false;
        function showAlert() {
            window.alertShown = true;
            alert('Test alert message');
            window.alertDismissed = true;
        }
    </script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Setup auto handler (accept=True is default)
        await setup_auto_dialog_handler(tab, accept=True)

        # Trigger alert
        await click(tab, selector="#alert-btn")
        await asyncio.sleep(0.3)

        # Verify alert was shown and dismissed
        shown = await tab.evaluate("window.alertShown")
        dismissed = await tab.evaluate("window.alertDismissed")
        assert shown is True
        assert dismissed is True

    async def test_no_dialog_returns_appropriate_result(self, browser):
        """Handling when no dialog present returns appropriate result."""
        tab = browser.main_tab

        html = """<!DOCTYPE html><html><body>No dialogs here</body></html>"""
        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # With wait_timeout=0, should return quickly with no dialog
        result = await handle_dialog_action(tab, accept=True, wait_timeout=0)
        # Either handled=False or no_dialog=True depending on implementation
        assert result.get("handled") is False or "error" in result or result.get("no_dialog")


class TestPageOperationsWorkflow:
    """Page operations: screenshot, HTML, eval, scroll.

    Covers: screenshot, get_page_html, eval_js, scroll, get_element_text
    """

    async def test_page_capture_workflow(self, browser):
        """Capture page state: screenshot, HTML, info."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><head><title>Test Page</title></head>
<body>
    <h1 id="title">Hello World</h1>
    <p id="content">This is test content.</p>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Screenshot
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "screenshot.png"
            result = await screenshot(tab, path=str(path))
            assert result.get("path") is not None
            assert Path(result["path"]).exists()

        # Get HTML
        html_result = await get_page_html(tab)
        assert "Hello World" in html_result.get("html", "")

        # Get page info
        info = await get_page_info(tab)
        assert "Test Page" in info.get("title", "")

        # Get element text
        text_result = await get_element_text(tab, selector="#content")
        assert "test content" in text_result.get("text", "").lower()

    async def test_scroll_workflow(self, browser):
        """Scroll through long page."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body style="height:3000px;">
    <div id="top">Top of page</div>
    <div id="bottom" style="position:absolute;bottom:0;">Bottom of page</div>
    <script>
        window.scrollEvents = [];
        window.addEventListener('scroll', () => {
            window.scrollEvents.push(window.scrollY);
        });
    </script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Scroll down
        await scroll(tab, direction="down", amount=500)
        await asyncio.sleep(0.1)
        scroll_y = await tab.evaluate("window.scrollY")
        assert scroll_y > 0

        # Scroll to bottom
        await scroll(tab, to_bottom=True)
        await asyncio.sleep(0.1)
        at_bottom = await tab.evaluate(
            "window.scrollY + window.innerHeight >= document.body.scrollHeight - 10"
        )
        assert at_bottom is True

        # Scroll to top
        await scroll(tab, to_top=True)
        await asyncio.sleep(0.1)
        scroll_y = await tab.evaluate("window.scrollY")
        assert scroll_y == 0

    async def test_eval_js_workflow(self, browser):
        """Execute JavaScript and get results."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <script>
        window.data = {
            users: [{name: 'Alice', age: 30}, {name: 'Bob', age: 25}],
            config: {theme: 'dark', language: 'en'}
        };
    </script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Eval simple expression
        result = await eval_js(tab, "1 + 1")
        assert result.get("result") == 2

        # Eval complex object access
        result = await eval_js(tab, "window.data.users.length")
        assert result.get("result") == 2

        # Eval with DOM
        result = await eval_js(tab, "document.body.tagName")
        assert result.get("result") == "BODY"


class TestWindowWorkflow:
    """Window management: resize, focus.

    Covers: resize_window, focus_window
    """

    async def test_resize_and_verify(self, browser):
        """Resize window and verify dimensions."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <script>
        window.resizeCount = 0;
        window.addEventListener('resize', () => window.resizeCount++);
    </script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Resize to specific dimensions
        result = await resize_window(tab, width=800, height=600)
        assert result.get("width") == 800
        assert result.get("height") == 600

        # Verify via JS
        await asyncio.sleep(0.2)
        inner_width = await tab.evaluate("window.innerWidth")
        inner_height = await tab.evaluate("window.innerHeight")
        # Inner dimensions might be slightly different due to browser chrome
        assert abs(inner_width - 800) < 50
        assert abs(inner_height - 600) < 100

    async def test_focus_window(self, browser):
        """Focus window."""
        tab = browser.main_tab

        result = await focus_window(tab)
        assert result.get("focused") is True


class TestDynamicContentWorkflow:
    """Dynamic content: wait for elements, interact with loaded content.

    Covers: wait_for_element, dynamic interaction patterns
    """

    async def test_wait_and_interact(self, browser):
        """Wait for dynamically loaded element then interact."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <div id="container"></div>
    <script>
        window.clicked = false;
        setTimeout(() => {
            const btn = document.createElement('button');
            btn.id = 'delayed-btn';
            btn.textContent = 'Click Me';
            btn.onclick = () => { window.clicked = true; };
            document.getElementById('container').appendChild(btn);
        }, 300);
    </script>
</body></html>"""

        await tab.get(make_data_url(html))

        # Wait for element to appear
        result = await wait_for_element(tab, selector="#delayed-btn", timeout=5)
        assert result.get("found") is True

        # Click the dynamically added button
        await click(tab, selector="#delayed-btn")
        clicked = await tab.evaluate("window.clicked")
        assert clicked is True

    async def test_content_update_after_action(self, browser):
        """Verify content updates after user action."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <button id="load-btn" onclick="loadContent()">Load Content</button>
    <div id="content"></div>
    <script>
        function loadContent() {
            document.getElementById('content').innerHTML = '<p id="loaded">Content loaded!</p>';
        }
    </script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Click to load content
        await click(tab, selector="#load-btn")

        # Wait for new content
        result = await wait_for_element(tab, selector="#loaded", timeout=2)
        assert result.get("found") is True

        # Verify content
        text = await get_element_text(tab, selector="#loaded")
        assert "loaded" in text.get("text", "").lower()


class TestTrustedEventsWorkflow:
    """Verify all interactions produce trusted events (anti-bot detection).

    Covers: click, type_text, mouse operations - all should have isTrusted=true
    """

    async def test_all_events_trusted(self, browser):
        """All user interactions should produce trusted events."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <button id="btn">Click</button>
    <input id="input" type="text">
    <script>
        window.events = [];
        document.addEventListener('click', e => {
            if (e.target.id) window.events.push({type:'click', target:e.target.id, trusted:e.isTrusted});
        });
        document.getElementById('input').addEventListener('input', e => {
            window.events.push({type:'input', trusted:e.isTrusted});
        });
        document.addEventListener('mousemove', e => {
            window.events.push({type:'mousemove', trusted:e.isTrusted});
        }, {once: true});
    </script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Mouse move
        await mouse_move(tab, 100, 100)

        # Click button
        await click(tab, selector="#btn")

        # Type in input
        await click(tab, selector="#input")
        await type_text(tab, "test", selector="#input")

        # Verify all events are trusted
        events = await eval_json(tab, "window.events")
        assert len(events) >= 3

        for event in events:
            assert event["trusted"] is True, f"Event {event['type']} should be trusted"
