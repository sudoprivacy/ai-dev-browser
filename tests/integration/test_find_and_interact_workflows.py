"""Find-and-interact workflows: discover elements, then click/type.

AI pattern: Use find() to discover page elements, then interact by ref or text.

Workflows covered:
- find → click_by_ref: Discover button, click by ref
- find → type_by_ref: Discover input, type by ref
- click_by_text / type_by_text: Direct text-based interaction
- Login forms, multi-step navigation, mixed patterns
"""

import asyncio
import base64
import json

from ai_dev_browser.core import (
    click_by_ref,
    click_by_text,
    find,
    focus_by_ref,
    goto,
    type_by_ref,
    type_by_text,
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


class TestFindAndClickByRef:
    """Workflow: find() → click_by_ref()

    AI pattern: Discover elements first, then click by ref.
    """

    async def test_find_button_click_by_ref(self, browser):
        """Find button in page, click by ref."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <button id="btn1">First Button</button>
    <button id="btn2">Second Button</button>
    <button id="btn3">Third Button</button>
    <script>
        window.clicks = [];
        document.querySelectorAll('button').forEach(btn => {
            btn.onclick = () => window.clicks.push(btn.id);
        });
    </script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Step 1: Find all elements
        result = await find(tab)
        elements = result.get("elements", [])

        # Step 2: Locate "Second Button" by name
        second_btn = None
        for el in elements:
            if el.get("name") == "Second Button":
                second_btn = el
                break

        assert second_btn is not None, "Should find 'Second Button'"
        assert second_btn.get("ref") is not None, "Element should have ref"

        # Step 3: Click by ref
        click_result = await click_by_ref(tab, ref=second_btn["ref"])
        assert click_result.get("clicked") is True

        # Verify correct button was clicked
        clicks = await eval_json(tab, "window.clicks")
        assert clicks == ["btn2"]

    async def test_find_link_click_by_ref(self, browser):
        """Find link and click by ref to navigate."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <a id="link1" href="#page1">Go to Page 1</a>
    <a id="link2" href="#page2">Go to Page 2</a>
    <script>
        window.navigated = null;
        document.querySelectorAll('a').forEach(a => {
            a.onclick = (e) => {
                e.preventDefault();
                window.navigated = a.id;
            };
        });
    </script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Find and click "Go to Page 2"
        result = await find(tab)
        link = next((el for el in result["elements"] if "Page 2" in el.get("name", "")), None)

        assert link is not None
        await click_by_ref(tab, ref=link["ref"])

        navigated = await tab.evaluate("window.navigated")
        assert navigated == "link2"

    async def test_find_interactable_only(self, browser):
        """Find with interactable_only=True filters non-interactive elements."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <h1>Title</h1>
    <p>Some paragraph text</p>
    <button>Click Me</button>
    <input type="text" placeholder="Type here">
    <span>Static text</span>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Find all elements
        all_result = await find(tab, interactable_only=False)
        all_elements = all_result.get("elements", [])

        # Find interactable only
        interactive_result = await find(tab, interactable_only=True)
        interactive_elements = interactive_result.get("elements", [])

        # Interactable should be subset
        assert len(interactive_elements) < len(all_elements)

        # Should include button and input
        roles = {el.get("role") for el in interactive_elements}
        assert "button" in roles or any("Click Me" in el.get("name", "") for el in interactive_elements)


class TestFindAndTypeByRef:
    """Workflow: find() → focus_by_ref() → type_by_ref()

    AI pattern: Discover input fields, focus, then type.
    """

    async def test_find_input_type_by_ref(self, browser):
        """Find input field and type by ref."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <input id="username" type="text" placeholder="Username">
    <input id="password" type="password" placeholder="Password">
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Find username input
        result = await find(tab)
        username_input = next(
            (el for el in result["elements"] if "Username" in el.get("name", "")),
            None
        )

        assert username_input is not None
        ref = username_input["ref"]

        # Type by ref
        type_result = await type_by_ref(tab, ref=ref, text="testuser")
        assert type_result.get("typed") is True

        # Verify value
        value = await tab.evaluate("document.getElementById('username').value")
        assert value == "testuser"

    async def test_focus_then_type_by_ref(self, browser):
        """Focus element first, then type."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <input id="search" type="text" placeholder="Search...">
    <script>
        window.focusEvents = [];
        document.getElementById('search').addEventListener('focus', () => {
            window.focusEvents.push('focused');
        });
    </script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Find search input
        result = await find(tab)
        search_input = next(
            (el for el in result["elements"] if "Search" in el.get("name", "")),
            None
        )

        assert search_input is not None
        ref = search_input["ref"]

        # Focus by ref
        focus_result = await focus_by_ref(tab, ref=ref)
        assert focus_result.get("focused") is True

        # Verify focus event fired
        focus_events = await eval_json(tab, "window.focusEvents")
        assert "focused" in focus_events

        # Type by ref
        await type_by_ref(tab, ref=ref, text="search query")
        value = await tab.evaluate("document.getElementById('search').value")
        assert value == "search query"

    async def test_type_by_ref_with_clear(self, browser):
        """Type by ref with clear=True to replace existing value."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <input id="field" type="text" value="existing value">
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Find field
        result = await find(tab)
        field = next(
            (el for el in result["elements"] if el.get("role") == "textbox"),
            None
        )

        assert field is not None

        # Type with clear
        await type_by_ref(tab, ref=field["ref"], text="new value", clear=True)

        value = await tab.evaluate("document.getElementById('field').value")
        assert value == "new value"


class TestClickByText:
    """Workflow: click_by_text() for text-based element interaction.

    AI pattern: Click elements by their visible text content.
    """

    async def test_click_button_by_text(self, browser):
        """Click button by its text content."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <button onclick="window.action='submit'">Submit Form</button>
    <button onclick="window.action='cancel'">Cancel</button>
    <button onclick="window.action='reset'">Reset</button>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Click by text
        result = await click_by_text(tab, text="Cancel")
        assert result.get("clicked") is True

        action = await tab.evaluate("window.action")
        assert action == "cancel"

    async def test_click_link_by_text(self, browser):
        """Click link by its text."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <a href="#" onclick="window.page='home'; return false;">Home</a>
    <a href="#" onclick="window.page='about'; return false;">About Us</a>
    <a href="#" onclick="window.page='contact'; return false;">Contact</a>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        await click_by_text(tab, text="About Us")

        page = await tab.evaluate("window.page")
        assert page == "about"

    async def test_click_by_text_partial_match(self, browser):
        """Click by text matches element containing the text."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <button onclick="window.clicked=true">Click here to continue</button>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Click by partial text
        await click_by_text(tab, text="Click here to continue")

        clicked = await tab.evaluate("window.clicked")
        assert clicked is True


class TestTypeByText:
    """Workflow: type_by_text() for text-based input interaction.

    AI pattern: Type into inputs identified by their label/placeholder.
    """

    async def test_type_by_placeholder_text(self, browser):
        """Type into input by its placeholder text."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <input type="text" placeholder="Enter your name">
    <input type="email" placeholder="Enter your email">
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Type by placeholder text
        result = await type_by_text(tab, name="Enter your email", text="test@example.com")
        assert result.get("typed") is True

        # Verify correct field was filled
        value = await tab.evaluate("document.querySelector('input[type=email]').value")
        assert value == "test@example.com"

    async def test_type_by_label_text(self, browser):
        """Type into input associated with a label."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <label for="username">Username</label>
    <input id="username" type="text">
    <label for="password">Password</label>
    <input id="password" type="password">
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Type by accessible name (label)
        await type_by_text(tab, name="Username", text="myuser")
        await type_by_text(tab, name="Password", text="mypass")

        username = await tab.evaluate("document.getElementById('username').value")
        password = await tab.evaluate("document.getElementById('password').value")

        assert username == "myuser"
        assert password == "mypass"


class TestLoginFormWorkflow:
    """Complete login form workflow using new APIs.

    Covers: find → type_by_ref → click_by_text (realistic AI usage)
    """

    async def test_login_form_with_ref_apis(self, browser):
        """Complete login using find + type_by_ref + click_by_text."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <form id="login-form">
        <h2>Login</h2>
        <input id="email" type="email" placeholder="Email address">
        <input id="pass" type="password" placeholder="Password">
        <label><input type="checkbox" id="remember"> Remember me</label>
        <button type="button" onclick="doLogin()">Sign In</button>
    </form>
    <div id="result"></div>
    <script>
        window.loginData = null;
        function doLogin() {
            window.loginData = {
                email: document.getElementById('email').value,
                password: document.getElementById('pass').value,
                remember: document.getElementById('remember').checked
            };
            document.getElementById('result').textContent = 'Login successful!';
        }
    </script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Step 1: Find all form elements
        result = await find(tab)
        elements = result.get("elements", [])

        # Step 2: Find email and password inputs by placeholder
        email_input = next((el for el in elements if "Email" in el.get("name", "")), None)
        pass_input = next((el for el in elements if "Password" in el.get("name", "")), None)

        assert email_input is not None, "Should find email input"
        assert pass_input is not None, "Should find password input"

        # Step 3: Type credentials by ref
        await type_by_ref(tab, ref=email_input["ref"], text="user@example.com")
        await type_by_ref(tab, ref=pass_input["ref"], text="secretpass123")

        # Step 4: Click login button by text
        await click_by_text(tab, text="Sign In")
        await asyncio.sleep(0.1)

        # Verify login data
        login_data = await eval_json(tab, "window.loginData")
        assert login_data is not None
        assert login_data["email"] == "user@example.com"
        assert login_data["password"] == "secretpass123"

    async def test_login_form_with_text_apis(self, browser):
        """Complete login using only text-based APIs."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <form>
        <input type="text" placeholder="Username">
        <input type="password" placeholder="Password">
        <button type="button" onclick="window.loggedIn=true">Login</button>
    </form>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # All text-based interactions
        await type_by_text(tab, name="Username", text="admin")
        await type_by_text(tab, name="Password", text="admin123")
        await click_by_text(tab, text="Login")

        logged_in = await tab.evaluate("window.loggedIn")
        assert logged_in is True


class TestMultiStepNavigationWorkflow:
    """Multi-page workflow: navigate → find → click → wait → verify.

    Covers: goto, find, click_by_ref, wait_for_element
    """

    async def test_navigate_find_click_sequence(self, browser):
        """Navigate to page, find element, click, verify result."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <h1>Product List</h1>
    <div class="product">
        <span>Product A</span>
        <button onclick="selectProduct('A')">Select</button>
    </div>
    <div class="product">
        <span>Product B</span>
        <button onclick="selectProduct('B')">Select</button>
    </div>
    <div id="selected" style="display:none;"></div>
    <script>
        function selectProduct(name) {
            document.getElementById('selected').textContent = 'Selected: ' + name;
            document.getElementById('selected').style.display = 'block';
        }
    </script>
</body></html>"""

        # Step 1: Navigate
        await goto(tab, make_data_url(html))
        await asyncio.sleep(0.2)

        # Step 2: Find all elements
        result = await find(tab)
        elements = result.get("elements", [])

        # Step 3: Find "Select" buttons - get the second one (Product B)
        select_buttons = [el for el in elements if el.get("name") == "Select"]
        assert len(select_buttons) >= 2

        # Step 4: Click second Select button
        await click_by_ref(tab, ref=select_buttons[1]["ref"])

        # Step 5: Wait for result to appear
        await wait_for_element(tab, selector="#selected", timeout=2)

        # Step 6: Verify
        selected_text = await tab.evaluate("document.getElementById('selected').textContent")
        assert "Product B" in selected_text

    async def test_dynamic_content_workflow(self, browser):
        """Handle dynamically loaded content with find and click."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <button id="load-btn" onclick="loadMore()">Load More</button>
    <div id="content"></div>
    <script>
        window.itemClicked = null;
        function loadMore() {
            setTimeout(() => {
                document.getElementById('content').innerHTML = `
                    <button onclick="window.itemClicked='item1'">Item 1</button>
                    <button onclick="window.itemClicked='item2'">Item 2</button>
                `;
            }, 200);
        }
    </script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Click load button
        await click_by_text(tab, text="Load More")

        # Wait for dynamic content
        await asyncio.sleep(0.3)

        # Find new elements
        result = await find(tab)
        item2 = next((el for el in result["elements"] if el.get("name") == "Item 2"), None)

        assert item2 is not None, "Should find dynamically loaded Item 2"

        # Click the dynamic element
        await click_by_ref(tab, ref=item2["ref"])

        clicked = await tab.evaluate("window.itemClicked")
        assert clicked == "item2"


class TestMixedApiWorkflow:
    """Workflow combining ref-based and text-based APIs.

    Real AI usage often mixes approaches based on context.
    """

    async def test_search_and_select_workflow(self, browser):
        """Search form (text-based) → Results (ref-based)."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <div id="search-section">
        <input type="text" placeholder="Search products...">
        <button onclick="doSearch()">Search</button>
    </div>
    <div id="results" style="display:none;">
        <button onclick="window.selected='result1'">Result 1</button>
        <button onclick="window.selected='result2'">Result 2</button>
        <button onclick="window.selected='result3'">Result 3</button>
    </div>
    <script>
        function doSearch() {
            const query = document.querySelector('input').value;
            if (query) {
                document.getElementById('results').style.display = 'block';
            }
        }
    </script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Phase 1: Text-based search
        await type_by_text(tab, name="Search products...", text="laptop")
        await click_by_text(tab, text="Search")

        await asyncio.sleep(0.1)

        # Phase 2: Ref-based result selection
        result = await find(tab)
        result2 = next((el for el in result["elements"] if el.get("name") == "Result 2"), None)

        assert result2 is not None
        await click_by_ref(tab, ref=result2["ref"])

        selected = await tab.evaluate("window.selected")
        assert selected == "result2"

    async def test_form_with_multiple_sections(self, browser):
        """Multi-section form with mixed interaction patterns."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <form>
        <fieldset>
            <legend>Personal Info</legend>
            <input type="text" placeholder="Full Name">
            <input type="email" placeholder="Email">
        </fieldset>
        <fieldset>
            <legend>Preferences</legend>
            <button type="button" onclick="window.pref='daily'">Daily Updates</button>
            <button type="button" onclick="window.pref='weekly'">Weekly Updates</button>
        </fieldset>
        <button type="button" onclick="submitForm()">Submit</button>
    </form>
    <script>
        window.formData = null;
        function submitForm() {
            window.formData = {
                name: document.querySelector('input[type=text]').value,
                email: document.querySelector('input[type=email]').value,
                pref: window.pref
            };
        }
    </script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        # Fill personal info (text-based - known placeholders)
        await type_by_text(tab, name="Full Name", text="John Doe")
        await type_by_text(tab, name="Email", text="john@example.com")

        # Select preference (find + ref - need to pick specific button)
        result = await find(tab)
        weekly_btn = next(
            (el for el in result["elements"] if el.get("name") == "Weekly Updates"),
            None
        )
        assert weekly_btn is not None
        await click_by_ref(tab, ref=weekly_btn["ref"])

        # Submit (text-based)
        await click_by_text(tab, text="Submit")
        await asyncio.sleep(0.1)

        # Verify
        form_data = await eval_json(tab, "window.formData")
        assert form_data["name"] == "John Doe"
        assert form_data["email"] == "john@example.com"
        assert form_data["pref"] == "weekly"


class TestTrustedEventsWithNewApis:
    """Verify new APIs produce trusted events (anti-bot detection)."""

    async def test_click_by_ref_trusted(self, browser):
        """click_by_ref should produce trusted events."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <button id="btn">Click</button>
    <script>
        window.eventTrusted = null;
        document.getElementById('btn').addEventListener('click', e => {
            window.eventTrusted = e.isTrusted;
        });
    </script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        result = await find(tab)
        btn = next((el for el in result["elements"] if el.get("name") == "Click"), None)
        await click_by_ref(tab, ref=btn["ref"])

        trusted = await tab.evaluate("window.eventTrusted")
        assert trusted is True

    async def test_click_by_text_trusted(self, browser):
        """click_by_text should produce trusted events."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <button>Test Button</button>
    <script>
        window.eventTrusted = null;
        document.querySelector('button').addEventListener('click', e => {
            window.eventTrusted = e.isTrusted;
        });
    </script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        await click_by_text(tab, text="Test Button")

        trusted = await tab.evaluate("window.eventTrusted")
        assert trusted is True

    async def test_type_by_ref_trusted(self, browser):
        """type_by_ref should produce trusted input events."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html><body>
    <input type="text" placeholder="Input">
    <script>
        window.inputTrusted = null;
        document.querySelector('input').addEventListener('input', e => {
            window.inputTrusted = e.isTrusted;
        });
    </script>
</body></html>"""

        await tab.get(make_data_url(html))
        await asyncio.sleep(0.2)

        result = await find(tab)
        input_el = next((el for el in result["elements"] if el.get("role") == "textbox"), None)
        await type_by_ref(tab, ref=input_el["ref"], text="test")

        trusted = await tab.evaluate("window.inputTrusted")
        assert trusted is True
