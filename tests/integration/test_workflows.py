"""Integration tests for complex multi-step workflows."""

import asyncio

from ai_dev_browser.core import click, human, mouse_click, mouse_move, type_text

from tests.conftest import eval_json


class TestFormWorkflow:
    """Test complete form filling workflows."""

    async def test_fill_form_and_submit(self, browser):
        """Complete form workflow: click fields, type, submit."""
        tab = browser.main_tab

        # Create a form page
        html = """<!DOCTYPE html>
<html>
<head>
    <style>
        input, button { padding: 10px; margin: 5px; display: block; }
        button { cursor: pointer; }
    </style>
</head>
<body>
    <form id="testForm">
        <input id="name" type="text" placeholder="Name">
        <input id="email" type="text" placeholder="Email">
        <input id="message" type="text" placeholder="Message">
        <button id="submit" type="button" onclick="submitForm()">Submit</button>
    </form>
    <div id="result"></div>
    <script>
        window.formData = null;
        window.submitCount = 0;
        function submitForm() {
            window.submitCount++;
            window.formData = {
                name: document.getElementById('name').value,
                email: document.getElementById('email').value,
                message: document.getElementById('message').value
            };
            document.getElementById('result').innerText = 'Submitted: ' + JSON.stringify(window.formData);
        }
    </script>
</body>
</html>"""

        import base64

        data_url = "data:text/html;base64," + base64.b64encode(html.encode()).decode()
        await tab.get(data_url)
        await asyncio.sleep(0.3)

        # Fill form: click -> type for each field
        await click(tab, selector="#name")
        await type_text(tab, "John Doe", selector="#name")

        await click(tab, selector="#email")
        await type_text(tab, "john@example.com", selector="#email")

        await click(tab, selector="#message")
        await type_text(tab, "Hello World!", selector="#message")

        # Submit
        await click(tab, selector="#submit")
        await asyncio.sleep(0.1)

        # Verify
        form_data = await eval_json(tab, "window.formData")
        assert form_data is not None
        assert form_data["name"] == "John Doe"
        assert form_data["email"] == "john@example.com"
        assert form_data["message"] == "Hello World!"

    async def test_form_with_clear_and_retype(self, browser):
        """Fill form, clear, and retype different values."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html>
<body>
    <input id="input1" type="text" value="initial value">
    <script>
        window.changes = [];
        document.getElementById('input1').addEventListener('input', function(e) {
            window.changes.push(e.target.value);
        });
    </script>
</body>
</html>"""

        import base64

        data_url = "data:text/html;base64," + base64.b64encode(html.encode()).decode()
        await tab.get(data_url)
        await asyncio.sleep(0.3)

        # Clear and type new value
        await click(tab, selector="#input1")
        await type_text(tab, "new value", selector="#input1", clear=True)

        # Verify final value
        value = await tab.evaluate("document.getElementById('input1').value")
        assert value == "new value"


class TestMouseContinuity:
    """Test mouse position continuity across operations."""

    async def test_long_sequence_mouse_operations(self, test_page):
        """50+ mouse operations should maintain position consistency."""
        positions = []

        for i in range(50):
            x = 100 + (i % 10) * 30
            y = 100 + (i // 10) * 30
            await mouse_move(test_page, x, y)

            # Verify position tracked correctly
            pos = human.get_last_mouse_pos(test_page)
            positions.append(pos)
            assert pos == (x, y), f"Position mismatch at iteration {i}"

        # All 50 positions should be unique (grid pattern)
        assert len(set(positions)) == 50

    async def test_move_click_move_sequence(self, test_page):
        """Mouse move -> click -> move should maintain continuity."""
        # Move to position
        await mouse_move(test_page, 200, 200)
        pos1 = human.get_last_mouse_pos(test_page)
        assert pos1 == (200, 200)

        # Get button position and click
        btn_pos = await eval_json(
            test_page,
            """
            (() => {
                const btn = document.getElementById('btn1');
                const rect = btn.getBoundingClientRect();
                return { x: rect.x + rect.width/2, y: rect.y + rect.height/2 };
            })()
        """,
        )

        await mouse_click(test_page, btn_pos["x"], btn_pos["y"])

        # Position should be at button
        pos2 = human.get_last_mouse_pos(test_page)
        assert abs(pos2[0] - btn_pos["x"]) <= 1
        assert abs(pos2[1] - btn_pos["y"]) <= 1

        # Move again
        await mouse_move(test_page, 300, 300)
        pos3 = human.get_last_mouse_pos(test_page)
        assert pos3 == (300, 300)


class TestTrustedEventChain:
    """Test that all events in a sequence are trusted (bot detection)."""

    async def test_all_clicks_trusted_in_sequence(self, test_page):
        """Multiple clicks should all have isTrusted=true."""
        trusted_values = []

        for _ in range(10):
            await click(test_page, selector="#btn1")
            event = await eval_json(test_page, "window.lastEvent")
            trusted_values.append(event["isTrusted"])

        # All events should be trusted
        assert all(trusted_values), "All click events should be trusted"

    async def test_mixed_operations_all_trusted(self, browser):
        """Click and type operations should all produce trusted events."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html>
<body>
    <button id="btn" onclick="window.btnClicked=true">Click</button>
    <input id="input" type="text">
    <script>
        window.events = [];
        document.addEventListener('click', e => window.events.push({type: 'click', trusted: e.isTrusted}));
        // CDP char events trigger 'input' event, not keydown
        document.getElementById('input').addEventListener('input', e => window.events.push({type: 'input', trusted: e.isTrusted}));
    </script>
</body>
</html>"""

        import base64

        data_url = "data:text/html;base64," + base64.b64encode(html.encode()).decode()
        await tab.get(data_url)
        await asyncio.sleep(0.3)

        # Perform mixed operations
        await click(tab, selector="#btn")
        await click(tab, selector="#input")
        await type_text(tab, "test", selector="#input")

        # Check all events are trusted
        events = await eval_json(tab, "window.events")
        click_events = [e for e in events if e["type"] == "click"]
        input_events = [e for e in events if e["type"] == "input"]

        assert len(click_events) >= 2
        assert all(e["trusted"] for e in click_events), "All clicks should be trusted"
        assert len(input_events) >= 1  # At least one input event from typing
        assert all(e["trusted"] for e in input_events), "All input events should be trusted"


class TestDynamicContent:
    """Test interaction with dynamically loaded content."""

    async def test_click_after_element_appears(self, browser):
        """Wait for element to appear, then click it."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html>
<body>
    <div id="container"></div>
    <script>
        window.clicked = false;
        setTimeout(() => {
            const btn = document.createElement('button');
            btn.id = 'delayed-btn';
            btn.innerText = 'Delayed Button';
            btn.onclick = () => { window.clicked = true; };
            document.getElementById('container').appendChild(btn);
        }, 500);
    </script>
</body>
</html>"""

        import base64

        data_url = "data:text/html;base64," + base64.b64encode(html.encode()).decode()
        await tab.get(data_url)

        # Wait for element to appear
        for _ in range(20):
            await asyncio.sleep(0.1)
            exists = await tab.evaluate("document.getElementById('delayed-btn') !== null")
            if exists:
                break

        # Click the dynamically added button
        await click(tab, selector="#delayed-btn")

        clicked = await tab.evaluate("window.clicked")
        assert clicked is True


class TestRapidOperations:
    """Test stability under rapid operation sequences."""

    async def test_rapid_clicks(self, test_page):
        """Many rapid clicks should all succeed."""
        # Reset click counter
        await test_page.evaluate("window.clicks = []")

        # Rapid clicks
        for _ in range(20):
            await click(test_page, selector="#btn1")

        clicks = await eval_json(test_page, "window.clicks")
        assert len(clicks) == 20, f"Expected 20 clicks, got {len(clicks)}"

    async def test_rapid_typing(self, browser):
        """Rapid typing in multiple fields."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html>
<body>
    <input id="i1" type="text">
    <input id="i2" type="text">
    <input id="i3" type="text">
</body>
</html>"""

        import base64

        data_url = "data:text/html;base64," + base64.b64encode(html.encode()).decode()
        await tab.get(data_url)
        await asyncio.sleep(0.3)

        # Type in multiple fields rapidly
        for i in range(1, 4):
            await click(tab, selector=f"#i{i}")
            await type_text(tab, f"value{i}", selector=f"#i{i}")

        # Verify all values
        for i in range(1, 4):
            value = await tab.evaluate(f"document.getElementById('i{i}').value")
            assert value == f"value{i}"
