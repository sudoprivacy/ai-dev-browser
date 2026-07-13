"""Element interaction operations."""

import asyncio
import json
import time


from . import human
from ._element import Element
from ._tab import Tab
from .ax import click_by_ref, get_element_by_ref
from .snapshot import _get_snapshot
from .text_match import _best_match


# Delay after click before reading post-click URL. Gives synchronous
# navigation a chance to start without blocking on events. For SPA
# client-side route changes this is usually enough; full-page loads
# trigger their own context destruction and the evaluate will handle it.
_POST_CLICK_NAV_DELAY = 0.3


async def _capture_page_state(tab: Tab) -> dict:
    """Read current top-level URL + title as a dict.

    Used before and after actions to report navigation feedback.
    """
    return await tab.evaluate("({url: window.location.href, title: document.title})")


# Poll interval while waiting for text to appear in the accessibility tree.
_AX_POLL_INTERVAL = 0.3


async def _ax_by_text(
    tab: Tab,
    text: str,
    interactable_only: bool = False,
) -> dict | None:
    """Locate an element by its *accessible name*. One shot, no waiting.

    The single answer to "where is the element labelled X", shared by every
    `*_by_text` tool so they cannot disagree with each other.

    Two tiers inside the accessibility tree: interactable elements (button /
    link / textbox) win, and only when none match does it fall back to
    non-interactable nodes. That fallback matters because Chrome reports a bare
    `<div onclick="...">` as StaticText — a real click target the strict tier
    would hide. Pass `interactable_only=True` to assert a genuine
    button/link/input carries the text.

    Why the AX tree and not `DOM.performSearch`: the accessible name is what a
    reader actually sees. It composes across element boundaries — Chrome reads
    `<button><Icon/><span>Sudo</span> <span>Code</span></button>` as the single
    name "Sudo Code", where a text-node search finds no node containing that
    string and returns nothing. It also spans same-origin iframes, and it
    resolves `<label for=x>` onto the input it labels, so typing by label lands
    in the field rather than on the label.

    Returns the element dict from `page_discover` (`ref`, `role`, `name`,
    `x`, `y`), or None.
    """
    from .snapshot import page_discover

    elements = await page_discover(tab, text=text, interactable_only=True)
    if elements:
        return _best_named(text, elements)
    if interactable_only:
        return None
    elements = await page_discover(tab, text=text, interactable_only=False)
    return _best_named(text, elements) if elements else None


def _best_named(query: str, candidates: list[dict]) -> dict:
    """Pick the candidate whose accessible name best matches `query`.

    `page_discover`'s text filter is a case-insensitive *substring* test and it
    yields matches in tree order, so a page with
    `<input placeholder="Search products…">` above `<button>Search</button>`
    hands back the input first for the query "Search". Taking the first hit
    would click the box instead of the button. Score instead, so an exact name
    beats a longer one that merely contains the query.
    """
    names = [c.get("name") or "" for c in candidates]
    best = _best_match(query, names)
    return candidates[best.index] if best else candidates[0]


async def _wait_ax_by_text(tab: Tab, text: str, timeout: float) -> dict | None:
    """`_ax_by_text`, retried until `timeout` — for the act-on-text tools,
    whose `timeout` promises to wait out an async render."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        hit = await _ax_by_text(tab, text)
        if hit:
            return hit
        if loop.time() >= deadline:
            return None
        await asyncio.sleep(_AX_POLL_INTERVAL)


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
    """Use when: the target element isn't in the viewport — lazy-loaded
    content, infinite scroll feed, or a long form. Returns `True` on
    success. Follow-ups: `page_discover` to see newly-rendered items,
    or a direct `click_by_*` / `find_by_*` if you know the locator.

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
    """Use when: an element is expected to appear asynchronously (after a
    navigation, XHR, SPA render) and you need to block until it's there
    before acting. Returns `{found, elapsed, message}` — then call the
    matching `click_*` / `type_*` to interact.

    Args:
        tab: Tab instance
        text: Text to wait for
        selector: CSS selector to wait for
        timeout: Maximum wait time in seconds

    Returns:
        dict with found, elapsed, message

    Failure:
        Element didn't appear within `timeout` seconds. Try a longer
        timeout if the page is slow; a broader locator (partial text
        instead of exact, less-specific CSS selector); or confirm the
        element is expected on this page via `page_discover`. For
        iframe-embedded targets with a text locator, note that
        text-based wait scans the top frame only — use
        `find_by_text` + `click_by_ref` pattern instead of waiting.
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
    """Use when: you know the element's visible text (button label, link
    anchor, menu item). Atomic locate+click, and it locates the same way
    `find_by_text` does — if `find_by_text` can see it, this can click it.

    Returns `{clicked, ref, url_before, url_after, title_after, navigated}` —
    **don't** screenshot after the click just to see if it worked,
    `navigated` + `url_after` already tell you. Only screenshot when you
    need to inspect visual state the return values can't express
    (form-validation error rendering, captcha pixels for OCR, final
    result view for the user).

    Matches on the element's *accessible name*, so it handles the two cases a
    raw text search misses: a label split across children
    (`<button><Icon/><span>Sudo</span> <span>Code</span></button>` reads as
    "Sudo Code"), and text inside same-origin iframes. A `<div onclick>` nav
    item works too — Chrome reports it as StaticText, and this clicks it anyway.

    Prefer when text is unique / unambiguous. For elements you already
    identified via `page_discover`, use `click_by_ref`.

    Args:
        tab: Tab instance
        text: Text content of the element to click
        timeout: How long to wait for the text to appear, in seconds
        human_like: Use the human-like actuator (default True, recommended)

    Returns:
        dict with clicked, text, ref, url_before, url_after, title_after,
        navigated. `navigated=True` means the top-level URL changed after the
        click (SPA route change or full page load).

    Failure:
        No element with this accessible name, in the main frame or any
        same-origin iframe, within `timeout`. Check spelling / case (matching is
        case-insensitive substring); try a shorter substring; raise `timeout` if
        the page renders late. Or switch locator — `click_by_html_id` /
        `click_by_xpath` when a DOM-level locator is known, or `page_discover`
        for a survey of what is actually on the page. Cross-origin iframes are
        not scanned.

    Example:
        click_by_text("登录")
        click_by_text("Sign in")
        click_by_text("Submit", timeout=5)
    """
    url_before_state = await _capture_page_state(tab)

    # Tier 1 — accessible name, the locator `find_by_text` uses. Shared on
    # purpose: two sibling tools that both claim to find "the element labelled
    # X" must never return different answers.
    located = await _wait_ax_by_text(tab, text, timeout)
    if located:
        result = await click_by_ref(tab, located["ref"], human_like=human_like)
        result["text"] = text
        return result

    # Tier 2 — DOM text-node search. Reached only when the AX tree has nothing,
    # and kept because it can still match what the tree never exposes: text
    # living in an attribute, and nodes Chrome omits from the tree. Its limits
    # (single text node, top frame only) are exactly why it is not tier 1.
    clicked = await _click(tab, text=text, timeout=0, human_like=human_like)
    action = {
        "clicked": clicked,
        "text": text,
        "url_before": url_before_state.get("url", ""),
    }
    if not clicked:
        action.update(
            {"navigated": False, "url_after": action["url_before"], "title_after": ""}
        )
        return action
    return await _with_nav_feedback(tab, action)


async def find_by_text(
    tab: Tab,
    text: str,
    interactable_only: bool = False,
) -> dict:
    """Use when: you know visible text and want to verify it exists or
    grab its `ref` before deciding whether to act — OR when
    `click_by_text` failed because the target is inside an iframe
    (this scans the full AX tree including same-origin iframes;
    `click_by_text` only scans the top frame). Returns
    `{found, ref, role, name, x, y}` for the first match — feed `ref`
    into `click_by_ref` / `type_by_ref` to act, or branch on
    `found=False`.

    Matching strategy (two-tier): interactable elements
    (button / link / textbox / etc.) are preferred — if any match the
    text, the first one wins. Only when NO interactable element
    matches does it fall back to non-interactable nodes (StaticText,
    headings, bare `<div onclick>` / `<span onclick>` that Chrome's
    accessibility tree reports as `StaticText`). This covers the
    Chinese-enterprise-system pattern of nav menus built from
    `<div onclick="...">` which Chrome does NOT mark as interactable,
    without regressing the common label-then-input case where the
    interactable match already wins.

    Pass `interactable_only=True` to disable the fallback and return
    `found=False` when no interactable match exists — useful when you
    want to assert "a real button/link with this text exists".

    For top-frame locate+click in one shot, use `click_by_text`
    directly. For elements identified by html id / xpath, use
    `find_by_html_id` / `find_by_xpath`. For broad page exploration
    without a known locator, use `page_discover`.

    Args:
        tab: Tab instance
        text: Visible text to match (case-insensitive substring)
        interactable_only: If True, only match interactable elements
            (buttons / links / inputs / etc.). Default False enables
            fallback to StaticText / div-with-onclick when no
            interactable element matches.

    Returns:
        dict: `{found: True, ref, role, name, x, y, ...}` on hit,
              `{found: False, text}` otherwise.

    Failure:
        Text not found in main frame or any same-origin iframe, in
        either the interactable or fallback tier. Check spelling /
        case (match is case-insensitive substring); try a shorter
        substring; or switch locator — `find_by_html_id` /
        `find_by_xpath` if a DOM-level locator is known. For a broad
        survey of what's on the page, run `page_discover` without a
        text filter. Cross-origin iframes are not scanned.
    """
    hit = await _ax_by_text(tab, text, interactable_only=interactable_only)
    if hit is None:
        return {"found": False, "text": text}
    return {"found": True, **hit}


async def type_by_text(
    tab: Tab,
    name: str,
    text: str,
    clear: bool = False,
    timeout: float = 10,
    human_like: bool = None,
) -> dict:
    """Use when: you know an input's visible label / placeholder / accessible
    name (e.g. "Email", "Search…"). Locates by AX name + types. Returns
    `{typed, name}`.

    Prefer over `type_by_ref` when you can identify the input by its
    human-visible label rather than needing a prior `page_discover` ref.

    Args:
        tab: Tab instance
        name: Accessible name to page_discover element (placeholder, label, etc.)
        text: Text to type into the element
        clear: If True, clear existing content first
        timeout: Search timeout in seconds
        human_like: Add delays between keystrokes (default: from config)

    Returns:
        dict with typed status

    Failure:
        No input with this accessible name, in the main frame or any same-origin
        iframe, within `timeout`. If the input has no accessible name at all
        (no label, no placeholder, no aria-label), locate it by html id or xpath
        instead: `find_by_html_id` / `find_by_xpath` → `type_by_ref`.
        Cross-origin iframes are not scanned.

    Example:
        type_by_text(name="用户名", text="myusername")
        type_by_text(name="Search", text="query", clear=True)
    """
    # Locator only — same accessible-name lookup as click_by_text / find_by_text.
    # Locating by AX name is what this tool has always *claimed* to do; it was
    # running a DOM text-node search, so a `<label for=email>Email</label>` match
    # landed on the label instead of the input it labels.
    #
    # The typing actuator below is deliberately left alone. Unlike clicking —
    # where the ref path could simply adopt the box-based actuator the text path
    # already used — `type_by_ref` types with `Input.insertText` while this types
    # per-character `char` events. Those produce different DOM event streams, so
    # routing one through the other would silently change which pages work.
    located = await _wait_ax_by_text(tab, name, timeout)
    if located is None:
        return {"typed": False, "error": f"Element with name '{name}' not found"}

    element = await get_element_by_ref(tab, located["ref"])
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

    return {"typed": True, "name": name, "ref": located["ref"]}


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
    """Use when: you already know the element's html `id` (from DOM inspection
    or a rendered template) and want to check existence / read its attrs
    without acting. Returns `{found, tag, text, visible, attrs}` you can
    branch on — then call `click_by_html_id` to act, or try a different
    locator if `found=False`. Cross-frame (same-origin).

    For broad exploration when you don't know what's on the page, use
    `page_discover` instead.

    Args:
        tab: Tab instance
        html_id: Value of the element's `id` attribute (e.g. `"login-btn"`).

    Returns:
        dict: `{found: true, tag, text, visible, attrs}` on hit,
              `{found: false}` otherwise.

    Failure:
        No element with this id in any same-origin frame. Use
        `page_discover` to see the ids actually present, or switch
        locator — `find_by_text` if you know the visible label,
        `find_by_xpath` for attribute-predicate / positional lookups.

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
    return await tab.evaluate(expr)


async def click_by_html_id(tab: Tab, html_id: str) -> dict:
    """Use when: you know the html `id` of the element you want clicked.
    Atomic locate+click in one call, cross-frame (same-origin).

    Returns `{clicked, url_before, url_after, title_after, navigated}` —
    **don't** screenshot after the click just to see if it worked,
    `navigated` + `url_after` already tell you. Only screenshot when you
    need to inspect visual state the return values can't express.

    Prefer over `click_by_ref` when you already know the id (skips the
    `page_discover` step). Prefer over `js_evaluate` — this is iframe-
    aware and gives you navigation feedback.

    Args:
        tab: Tab instance
        html_id: Value of the element's `id` attribute.

    Returns:
        dict: `{clicked, html_id, url_before, url_after, title_after, navigated, error?}`.
        `navigated=True` means the top-level URL changed after the click.

    Failure:
        No element with this id found in any same-origin frame. Run
        `find_by_html_id` first to verify existence and get attrs, or
        switch locator — `click_by_text` (top frame only, use
        `find_by_text` → `click_by_ref` for iframe targets) or
        `click_by_xpath` for attribute / positional predicates.
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
    click = await tab.evaluate(expr)
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
    """Use when: the element is best expressed as an XPath — attribute
    predicate (`//button[@data-role='confirm']`), positional
    (`//div[@class='results']/a[3]`), or anything `page_discover` / text
    match can't disambiguate. Returns `{found, tag, text, visible, attrs}`
    you branch on. Pair with `click_by_xpath` to act. Cross-frame
    (same-origin).

    Args:
        tab: Tab instance
        xpath: XPath expression. Runs via `document.evaluate()`.

    Returns:
        dict: `{found: true, tag, text, visible, attrs}` on hit,
              `{found: false}` otherwise.

    Failure:
        XPath returned no match in any same-origin frame. Shorten the
        expression (e.g. `//button` instead of
        `//button[@data-role='x']`) to verify the broader target
        exists, or switch locator — `find_by_text` by visible label,
        `find_by_html_id` if an id is known, or `page_discover` for a
        structural survey.
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
    return await tab.evaluate(expr)


async def click_by_xpath(tab: Tab, xpath: str) -> dict:
    """Use when: the element is best expressed as an XPath (attribute
    predicate, positional, or anything text/ref can't disambiguate).
    Atomic locate+click, cross-frame (same-origin). Prefer over
    `js_evaluate` for locate+click.

    Returns `{clicked, url_before, url_after, title_after, navigated}` —
    **don't** screenshot after the click just to see if it worked,
    `navigated` + `url_after` already tell you. Only screenshot when you
    need to inspect visual state the return values can't express.

    Args:
        tab: Tab instance
        xpath: XPath expression (e.g. `//button[contains(text(), 'Submit')]`).

    Returns:
        dict: `{clicked, xpath, url_before, url_after, title_after, navigated, error?}`.

    Failure:
        XPath returned no match in any same-origin frame. Verify with
        `find_by_xpath` first (returns the matched element's attrs
        without clicking), or switch locator — `click_by_text` /
        `click_by_html_id`, or `page_discover` → `click_by_ref`.
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
    click = await tab.evaluate(expr)
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
