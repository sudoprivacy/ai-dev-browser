"""Element interaction operations."""

import asyncio
import json
import time


from . import human
from ._element import Element
from ._tab import Tab
from .snapshot import _get_snapshot
from .text_match import _best_match


# Delay after click before reading post-click URL. Gives synchronous
# navigation a chance to start without blocking on events. For SPA
# client-side route changes this is usually enough; full-page loads
# trigger their own context destruction and the evaluate will handle it.
_POST_CLICK_NAV_DELAY = 0.3


async def _json_evaluate(tab: Tab, expression: str) -> dict:
    """Evaluate JS that returns a JSON-serializable value and parse it Python-side.

    Why: Tab.evaluate passes serialization_options=deep to CDP alongside
    return_by_value, and the deep-serialized shape is `[[key, typed_value], ...]`
    which isn't a plain Python dict. JSON.stringify round-tripping is the most
    reliable way to get a plain dict out.
    """
    raw = await tab.evaluate(f"JSON.stringify(({expression}))")
    if not isinstance(raw, str):
        return {}
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}


async def _capture_page_state(tab: Tab) -> dict:
    """Read current top-level URL + title as a JSON dict.

    Used before and after actions to report navigation feedback.
    """
    return await _json_evaluate(
        tab, "{url: window.location.href, title: document.title}"
    )


async def _with_nav_feedback(tab: Tab, action_result: dict) -> dict:
    """Attach navigation feedback fields to a click-result dict.

    Caller is expected to have captured url_before before the action and
    passed it in via action_result (the action function adds it). This
    helper completes the post-click read after _POST_CLICK_NAV_DELAY and
    returns {..., navigated, url_after, title_after}.
    """
    url_before = action_result.get("url_before", "")
    await asyncio.sleep(_POST_CLICK_NAV_DELAY)
    try:
        after = await _capture_page_state(tab)
    except Exception:
        # Context destroyed by full-page nav mid-read — we know it navigated
        action_result["navigated"] = True
        action_result["url_after"] = None
        action_result["title_after"] = None
        return action_result
    action_result["url_after"] = after.get("url", "")
    action_result["title_after"] = after.get("title", "")
    action_result["navigated"] = (
        bool(url_before) and action_result["url_after"] != url_before
    )
    return action_result


async def _find_element(
    tab: Tab,
    text: str | None = None,
    selector: str | None = None,
    timeout: float = 10,
) -> dict:
    """Find single element by text or selector.

    Args:
        tab: Tab instance
        text: Text to search for
        selector: CSS selector
        timeout: Search timeout in seconds

    Returns:
        dict with found, element (for programmatic use)
    """
    element = None
    if text:
        element = await tab.find(text, timeout=timeout)
    elif selector:
        element = await tab.select(selector, timeout=timeout)

    return {
        "found": element is not None,
        "element": element,
    }


async def _find_elements(
    tab: Tab,
    text: str | None = None,
    selector: str | None = None,
    timeout: float = 10,
) -> dict:
    """Find all matching elements.

    Args:
        tab: Tab instance
        text: Text to search for
        selector: CSS selector
        timeout: Search timeout in seconds

    Returns:
        dict with count, elements (for programmatic use)
    """
    elements = []
    if text:
        elements = await tab.find_all(text, timeout=timeout)
    elif selector:
        elements = await tab.select_all(selector, timeout=timeout)

    return {
        "count": len(elements),
        "elements": elements,
    }


async def _find_by_xpath(
    tab: Tab,
    xpath: str,
    timeout: float = 2.5,
) -> dict:
    """Find elements by XPath.

    Args:
        tab: Tab instance
        xpath: XPath expression
        timeout: Search timeout in seconds

    Returns:
        dict with count, elements (for programmatic use)
    """
    elements = await tab.xpath(xpath, timeout=timeout)
    return {
        "found": len(elements) > 0,
        "count": len(elements),
        "elements": elements,
    }


async def _click(
    tab: Tab,
    element: Element | None = None,
    text: str | None = None,
    selector: str | None = None,
    timeout: float = 10,
    human_like: bool = True,
) -> bool:
    """Click on element.

    Uses CDP mouse events by default (isTrusted=true) instead of JS click.
    Applies random offset within element bounds for more human-like behavior.

    Args:
        tab: Tab instance
        element: Element to click (if already found)
        text: Text to page_discover and click
        selector: CSS selector to page_discover and click
        timeout: Search timeout in seconds
        human_like: Use CDP events + offset (default True, recommended)

    Returns:
        True if clicked successfully
    """
    if element is None:
        result = await _find_element(tab, text=text, selector=selector, timeout=timeout)
        element = result.get("element")

    if element:
        if human_like:
            # Use CDP events (isTrusted=true) with optional offset
            await human.click_element(tab, element)
        else:
            # Use JS click (isTrusted=false, detectable but faster)
            await element.click()
        return True
    return False


async def _type_text(
    tab: Tab,
    text: str,
    element: Element | None = None,
    selector: str | None = None,
    clear: bool = False,
    timeout: float = 10,
    human_like: bool = None,
) -> bool:
    """Type text into element.

    Args:
        tab: Tab instance
        text: Text to type
        element: Element to type into (if already found)
        selector: CSS selector to page_discover element
        clear: If True, clear existing content first
        timeout: Search timeout in seconds
        human_like: Add delays between keystrokes (default: from config)

    Returns:
        True if typed successfully
    """
    if element is None and selector:
        result = await _find_element(tab, selector=selector, timeout=timeout)
        element = result.get("element")

    if element is None:
        return False

    if clear:
        await element.clear_input()

    # Determine whether to use human-like typing
    use_human = (
        human_like if human_like is not None else human.get_config().type_humanize
    )

    if use_human:
        await human.type_text(tab, text, element, humanize=True)
    else:
        await element.send_keys(text)
    return True


async def page_scroll(
    tab: Tab,
    direction: str = "down",
    amount: int = 25,
    to_bottom: bool = False,
    to_top: bool = False,
    to_element: Element | None = None,
) -> bool:
    """Scroll the page.

    Args:
        tab: Tab instance
        direction: "up" or "down"
        amount: Scroll amount (percentage)
        to_bottom: Scroll to bottom of page
        to_top: Scroll to top of page
        to_element: Scroll element into view

    Returns:
        True on success
    """
    if to_element:
        await to_element.scroll_into_view()
    elif to_bottom:
        await tab.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    elif to_top:
        await tab.evaluate("window.scrollTo(0, 0)")
    elif direction == "up":
        await tab.scroll_up(amount)
    else:
        await tab.scroll_down(amount)
    return True


async def _wait_for_element(
    tab: Tab,
    text: str | None = None,
    selector: str | None = None,
    timeout: float = 30,
) -> dict:
    """Wait for element to appear.

    Args:
        tab: Tab instance
        text: Text to wait for
        selector: CSS selector to wait for
        timeout: Maximum wait time in seconds

    Returns:
        dict with found, elapsed
    """
    start_time = time.time()

    while True:
        elapsed = time.time() - start_time

        if elapsed > timeout:
            return {
                "found": False,
                "elapsed": round(elapsed, 2),
            }

        try:
            if text:
                element = await tab.find(text, timeout=1)
                if element:
                    return {
                        "found": True,
                        "elapsed": round(elapsed, 2),
                    }
            elif selector:
                js_code = f"document.querySelector({repr(selector)}) !== null"
                found = await tab.evaluate(js_code)
                if found:
                    return {
                        "found": True,
                        "elapsed": round(elapsed, 2),
                    }
        except Exception:
            pass

        await asyncio.sleep(0.5)


async def _focus_element(
    tab: Tab,
    text: str | None = None,
    selector: str | None = None,
    timeout: float = 10,
) -> dict:
    """Focus an element by selector or text.

    Args:
        tab: Tab instance
        text: Text to page_discover element by
        selector: CSS selector

    Returns:
        dict with focused status
    """
    result = await _find_element(tab, text=text, selector=selector, timeout=timeout)
    if result["found"] and result["element"]:
        await result["element"].focus()
        return {"focused": True}
    return {"focused": False, "error": "Element not found"}


async def _get_element_text(
    tab: Tab,
    text: str | None = None,
    selector: str | None = None,
    timeout: float = 10,
) -> dict:
    """Get text content of an element.

    Args:
        tab: Tab instance
        text: Text to page_discover element by
        selector: CSS selector

    Returns:
        dict with text content
    """
    result = await _find_element(tab, text=text, selector=selector, timeout=timeout)
    if result["found"] and result["element"]:
        # Use text_all property which is synchronous
        content = result["element"].text_all
        return {"text": content if content else ""}
    return {"text": None, "error": "Element not found"}


async def _find_element_info(
    tab: Tab,
    text: str | None = None,
    selector: str | None = None,
    all_elements: bool = False,
    timeout: float = 10,
) -> dict:
    """Find element(s) and return info suitable for CLI/script use.

    Args:
        tab: Tab instance
        text: Text to search for
        selector: CSS selector
        all_elements: If True, page_discover all matching elements
        timeout: Search timeout in seconds

    Returns:
        dict with found, count (if all), tag, text (for single element)
    """
    if all_elements:
        result = await _find_elements(
            tab, text=text, selector=selector, timeout=timeout
        )
        return {
            "found": result["count"] > 0,
            "count": result["count"],
        }
    else:
        result = await _find_element(tab, text=text, selector=selector, timeout=timeout)
        element = result.get("element")
        if element:
            # Get element info
            tag = await element.apply("(el) => el.tagName.toLowerCase()")
            text_content = await element.apply("(el) => el.textContent.slice(0, 100)")
            return {
                "found": True,
                "tag": tag,
                "text": text_content.strip() if text_content else "",
            }
        return {"found": False}


async def page_wait_element(
    tab: Tab,
    text: str | None = None,
    selector: str | None = None,
    timeout: float = 30,
) -> dict:
    """Wait for element to appear with descriptive message.

    Args:
        tab: Tab instance
        text: Text to wait for
        selector: CSS selector to wait for
        timeout: Maximum wait time in seconds

    Returns:
        dict with found, elapsed, message
    """
    result = await _wait_for_element(tab, text=text, selector=selector, timeout=timeout)

    # Add descriptive message
    if result.get("found"):
        if text:
            result["message"] = f"Element with text '{text}' found"
        else:
            result["message"] = f"Element '{selector}' found"
    else:
        result["message"] = f"Timeout after {timeout}s"

    return result


async def click_by_text(
    tab: Tab,
    text: str,
    timeout: float = 10,
    human_like: bool = True,
) -> dict:
    """Click element by text content.

    This is the primary way for AI to click elements. Use page_discover() first to
    see available elements, then click_by_text with the exact text.

    Args:
        tab: Tab instance
        text: Text content of the element to click
        timeout: Search timeout in seconds
        human_like: Use CDP events (default True, recommended)

    Returns:
        dict with clicked, text, url_before, url_after, title_after, navigated.
        `navigated=True` means the top-level URL changed after the click
        (SPA route change or full page load). Use this to confirm the click
        had the intended side effect instead of chaining a screenshot + discover.

    Example:
        click_by_text("登录")
        click_by_text("Sign in")
        click_by_text("Submit", timeout=5)
    """
    url_before_state = await _capture_page_state(tab)
    result = await _click(tab, text=text, timeout=timeout, human_like=human_like)
    action = {
        "clicked": result,
        "text": text,
        "url_before": url_before_state.get("url", ""),
    }
    if not result:
        action.update(
            {"navigated": False, "url_after": action["url_before"], "title_after": ""}
        )
        return action
    return await _with_nav_feedback(tab, action)


async def type_by_text(
    tab: Tab,
    name: str,
    text: str,
    clear: bool = False,
    timeout: float = 10,
    human_like: bool = None,
) -> dict:
    """Type text into element located by its accessible name.

    Use page_discover() first to see element names (placeholder, label, etc.),
    then type_by_text with the name.

    Args:
        tab: Tab instance
        name: Accessible name to page_discover element (placeholder, label, etc.)
        text: Text to type into the element
        clear: If True, clear existing content first
        timeout: Search timeout in seconds
        human_like: Add delays between keystrokes (default: from config)

    Returns:
        dict with typed status

    Example:
        type_by_text(name="用户名", text="myusername")
        type_by_text(name="Search", text="query", clear=True)
    """
    result = await _find_element(tab, text=name, timeout=timeout)
    element = result.get("element")

    if element is None:
        return {"typed": False, "error": f"Element with name '{name}' not found"}

    if clear:
        await element.clear_input()

    use_human = (
        human_like if human_like is not None else human.get_config().type_humanize
    )

    if use_human:
        await human.type_text(tab, text, element, humanize=True)
    else:
        await element.send_keys(text)

    return {"typed": True, "name": name}


# ---------------------------------------------------------------------------
# Fuzzy matching functions (accessibility tree + text_match scoring)
# ---------------------------------------------------------------------------


async def _fuzzy_find(
    tab: Tab,
    query: str,
    threshold: float = 0.4,
    interactable_only: bool = False,
) -> dict | None:
    """Find element by fuzzy text matching against accessibility tree.

    Uses exact > contains > edit distance scoring to page_discover the best
    matching element. Works with aria-labels, button text, and other
    accessible names - stable identifiers ideal for scripting.

    Args:
        tab: Tab instance
        query: Text to search for (supports fuzzy matching)
        threshold: Minimum match score (0.0-1.0)
        interactable_only: Only match interactive elements (buttons, links, inputs)

    Returns:
        Dict with element info and match details, or None if not found.
        Keys: ref, role, name, _nodeId, match_score, match_strategy
    """
    elements = await _get_snapshot(tab, interactable_only=interactable_only)
    if not elements:
        return None

    # Build candidates list from element names
    names = [el.get("name", "") for el in elements]
    result = _best_match(query, names, threshold=threshold)

    if result is None:
        return None

    matched_element = elements[result.index]
    return {
        **matched_element,
        "match_score": round(result.score, 3),
        "match_strategy": result.strategy,
    }


async def _fuzzy_find_all(
    tab: Tab,
    query: str,
    threshold: float = 0.4,
    interactable_only: bool = False,
    limit: int = 10,
) -> list[dict]:
    """Find all elements matching query by fuzzy text matching.

    Args:
        tab: Tab instance
        query: Text to search for
        threshold: Minimum match score (0.0-1.0)
        interactable_only: Only match interactive elements
        limit: Maximum number of results

    Returns:
        List of element dicts sorted by match score descending
    """
    from .text_match import _all_matches

    elements = await _get_snapshot(tab, interactable_only=interactable_only)
    if not elements:
        return []

    names = [el.get("name", "") for el in elements]
    matches = _all_matches(query, names, threshold=threshold, limit=limit)

    return [
        {
            **elements[m.index],
            "match_score": round(m.score, 3),
            "match_strategy": m.strategy,
        }
        for m in matches
    ]


async def _fuzzy_click(
    tab: Tab,
    query: str,
    threshold: float = 0.4,
    interactable_only: bool = True,
    human_like: bool = True,
) -> dict | None:
    """Click element by fuzzy text matching against accessibility tree.

    Combines fuzzy_find + click. The primary API for programmatic
    browser automation scripts that need tolerance for text variations.

    Args:
        tab: Tab instance
        query: Text to match (e.g., "Upload files", "Sign in")
        threshold: Minimum match score (0.0-1.0)
        interactable_only: Only match interactive elements (default: True)
        human_like: Use CDP events (default True, recommended)

    Returns:
        Dict with clicked element info, or None if not found/click failed.

    Example:
        # Stable scripting - no AI needed
        await fuzzy_click(tab, "Upload files")
        await fuzzy_click(tab, "Sign in")
        await fuzzy_click(tab, "Submit")
    """
    from .ax import _click_by_node_id

    match = await _fuzzy_find(
        tab,
        query,
        threshold=threshold,
        interactable_only=interactable_only,
    )
    if match is None:
        return None

    node_id = match.get("_nodeId")
    if not node_id:
        return None

    result = await _click_by_node_id(tab, node_id)
    if result.get("clicked"):
        return {
            "clicked": True,
            "ref": match.get("ref"),
            "role": match.get("role"),
            "name": match.get("name"),
            "match_score": match.get("match_score"),
            "match_strategy": match.get("match_strategy"),
        }
    return None


# =============================================================================
# Direct DOM locators — cover cases the accessibility tree can't express
# (cross-frame html-id lookup, XPath queries). Complement page_discover:
#   - page_discover:   broad exploration of the accessibility tree
#   - find_by_*:       targeted single-element lookup by html locator
# =============================================================================


# Shared JS snippet that, given an element (possibly null), returns a
# serializable info dict or {found: false}. Inlined inside each IIFE so the
# concatenation stays a single expression — a prior version put this outside
# the IIFE and JavaScript parsed `function decl(...) (IIFE)` as
# `decl(IIFE_result)` instead of two separate statements.
_ELEMENT_INFO_INLINE = """
        const __elementInfo = (el) => {
          if (!el) return {found: false};
          let rect = {width: 0, height: 0};
          try { rect = el.getBoundingClientRect(); } catch(e) {}
          return {
            found: true,
            tag: (el.tagName || '').toLowerCase(),
            text: ((el.innerText || el.textContent || '') + '').trim().slice(0, 200),
            visible: rect.width > 0 && rect.height > 0 && el.offsetParent !== null,
            attrs: {
              id: el.id || null,
              name: el.getAttribute ? el.getAttribute('name') : null,
              type: el.getAttribute ? el.getAttribute('type') : null,
              'aria-label': el.getAttribute ? el.getAttribute('aria-label') : null,
            }
          };
        };"""


async def find_by_html_id(tab: Tab, html_id: str) -> dict:
    """Find an element by its html `id` attribute, recursing into same-origin iframes.

    For broad page exploration see `page_discover`. Use this when you already
    know the specific html `id` (from DOM inspection, prior HTML snapshot, or
    a rendered template).

    Args:
        tab: Tab instance
        html_id: Value of the element's `id` attribute (e.g. `"login-btn"`).

    Returns:
        dict: `{found: true, tag, text, visible, attrs}` on hit,
              `{found: false}` otherwise.

    Example:
        result = await find_by_html_id(tab, "submit-btn")
        if result["found"] and result["visible"]:
            await click_by_html_id(tab, "submit-btn")
    """
    expr = """
    (function(id) {
      %s
      function search(win) {
        try {
          const el = win.document.getElementById(id);
          if (el) return el;
        } catch(e) {}
        for (let i = 0; i < win.frames.length; i++) {
          try {
            const result = search(win.frames[i]);
            if (result) return result;
          } catch(e) {}
        }
        return null;
      }
      return __elementInfo(search(window));
    })(%s)
    """ % (_ELEMENT_INFO_INLINE, json.dumps(html_id))
    return await _json_evaluate(tab, expr)


async def click_by_html_id(tab: Tab, html_id: str) -> dict:
    """Click an element located by html `id`, recursing into same-origin iframes.

    Unlike `click_by_ref` (accessibility tree) and `click_by_text`
    (visible text), this targets a specific `id` attribute — useful when
    the element lives inside a frame or the accessibility tree doesn't
    surface it.

    Args:
        tab: Tab instance
        html_id: Value of the element's `id` attribute.

    Returns:
        dict: `{clicked, html_id, url_before, url_after, title_after, navigated, error?}`.
        `navigated=True` means the top-level URL changed after the click.
    """
    url_before_state = await _capture_page_state(tab)
    url_before = url_before_state.get("url", "")

    expr = """
    (function(id) {
      function search(win) {
        try {
          const el = win.document.getElementById(id);
          if (el) return el;
        } catch(e) {}
        for (let i = 0; i < win.frames.length; i++) {
          try {
            const result = search(win.frames[i]);
            if (result) return result;
          } catch(e) {}
        }
        return null;
      }
      const el = search(window);
      if (!el) return {clicked: false, error: 'not found'};
      try {
        el.click();
        return {clicked: true};
      } catch(e) {
        return {clicked: false, error: String(e)};
      }
    })(%s)
    """ % json.dumps(html_id)
    click = await _json_evaluate(tab, expr)
    action = {
        "clicked": bool(click.get("clicked")),
        "html_id": html_id,
        "url_before": url_before,
    }
    if click.get("error"):
        action["error"] = click["error"]
    if not action["clicked"]:
        action.update({"navigated": False, "url_after": url_before, "title_after": ""})
        return action
    return await _with_nav_feedback(tab, action)


async def find_by_xpath(tab: Tab, xpath: str) -> dict:
    """Find the first element matching an XPath expression, recursing into
    same-origin iframes.

    For broad page exploration see `page_discover`. Use this when the
    accessibility tree doesn't surface the element you need or when an
    XPath is the most natural locator (e.g. `//button[@title='登录']`).

    Args:
        tab: Tab instance
        xpath: XPath expression. Runs via `document.evaluate()`.

    Returns:
        dict: `{found: true, tag, text, visible, attrs}` on hit,
              `{found: false}` otherwise.
    """
    expr = """
    (function(xpath) {
      %s
      function search(doc) {
        try {
          const result = doc.evaluate(xpath, doc, null,
                                      XPathResult.FIRST_ORDERED_NODE_TYPE, null);
          if (result && result.singleNodeValue) return result.singleNodeValue;
        } catch(e) {}
        return null;
      }
      function recurse(win) {
        try {
          const hit = search(win.document);
          if (hit) return hit;
        } catch(e) {}
        for (let i = 0; i < win.frames.length; i++) {
          try {
            const hit = recurse(win.frames[i]);
            if (hit) return hit;
          } catch(e) {}
        }
        return null;
      }
      return __elementInfo(recurse(window));
    })(%s)
    """ % (_ELEMENT_INFO_INLINE, json.dumps(xpath))
    return await _json_evaluate(tab, expr)


async def click_by_xpath(tab: Tab, xpath: str) -> dict:
    """Click the first element matching an XPath expression, recursing into
    same-origin iframes.

    Args:
        tab: Tab instance
        xpath: XPath expression (e.g. `//button[contains(text(), 'Submit')]`).

    Returns:
        dict: `{clicked, xpath, url_before, url_after, title_after, navigated, error?}`.
    """
    url_before_state = await _capture_page_state(tab)
    url_before = url_before_state.get("url", "")

    expr = """
    (function(xpath) {
      function search(doc) {
        try {
          const result = doc.evaluate(xpath, doc, null,
                                      XPathResult.FIRST_ORDERED_NODE_TYPE, null);
          if (result && result.singleNodeValue) return result.singleNodeValue;
        } catch(e) {}
        return null;
      }
      function recurse(win) {
        try {
          const hit = search(win.document);
          if (hit) return hit;
        } catch(e) {}
        for (let i = 0; i < win.frames.length; i++) {
          try {
            const hit = recurse(win.frames[i]);
            if (hit) return hit;
          } catch(e) {}
        }
        return null;
      }
      const el = recurse(window);
      if (!el) return {clicked: false, error: 'not found'};
      try {
        el.click();
        return {clicked: true};
      } catch(e) {
        return {clicked: false, error: String(e)};
      }
    })(%s)
    """ % json.dumps(xpath)
    click = await _json_evaluate(tab, expr)
    action = {
        "clicked": bool(click.get("clicked")),
        "xpath": xpath,
        "url_before": url_before,
    }
    if click.get("error"):
        action["error"] = click["error"]
    if not action["clicked"]:
        action.update({"navigated": False, "url_after": url_before, "title_after": ""})
        return action
    return await _with_nav_feedback(tab, action)
