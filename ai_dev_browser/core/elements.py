"""Element interaction operations."""

import asyncio
import time

import nodriver
import nodriver.cdp.dom as dom

from . import human
from .snapshot import get_snapshot


async def find_element(
    tab: nodriver.Tab,
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


async def find_elements(
    tab: nodriver.Tab,
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


async def find_by_xpath(
    tab: nodriver.Tab,
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


async def click(
    tab: nodriver.Tab,
    element: nodriver.Element | None = None,
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
        text: Text to find and click
        selector: CSS selector to find and click
        timeout: Search timeout in seconds
        human_like: Use CDP events + offset (default True, recommended)

    Returns:
        True if clicked successfully
    """
    if element is None:
        result = await find_element(tab, text=text, selector=selector, timeout=timeout)
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


async def type_text(
    tab: nodriver.Tab,
    text: str,
    element: nodriver.Element | None = None,
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
        selector: CSS selector to find element
        clear: If True, clear existing content first
        timeout: Search timeout in seconds
        human_like: Add delays between keystrokes (default: from config)

    Returns:
        True if typed successfully
    """
    if element is None and selector:
        result = await find_element(tab, selector=selector, timeout=timeout)
        element = result.get("element")

    if element is None:
        return False

    if clear:
        await element.clear_input()

    # Determine whether to use human-like typing
    use_human = human_like if human_like is not None else human.get_config().type_humanize

    if use_human:
        await human.type_text(tab, text, element, humanize=True)
    else:
        await element.send_keys(text)
    return True


async def scroll(
    tab: nodriver.Tab,
    direction: str = "down",
    amount: int = 25,
    to_bottom: bool = False,
    to_top: bool = False,
    to_element: nodriver.Element | None = None,
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


async def wait_for_element(
    tab: nodriver.Tab,
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


async def focus_element(
    tab: nodriver.Tab,
    text: str | None = None,
    selector: str | None = None,
    timeout: float = 10,
) -> dict:
    """Focus an element by selector or text.

    Args:
        tab: Tab instance
        text: Text to find element by
        selector: CSS selector

    Returns:
        dict with focused status
    """
    result = await find_element(tab, text=text, selector=selector, timeout=timeout)
    if result["found"] and result["element"]:
        await result["element"].focus()
        return {"focused": True}
    return {"focused": False, "error": "Element not found"}


async def get_element_text(
    tab: nodriver.Tab,
    text: str | None = None,
    selector: str | None = None,
    timeout: float = 10,
) -> dict:
    """Get text content of an element.

    Args:
        tab: Tab instance
        text: Text to find element by
        selector: CSS selector

    Returns:
        dict with text content
    """
    result = await find_element(tab, text=text, selector=selector, timeout=timeout)
    if result["found"] and result["element"]:
        # Use text_all property which is synchronous
        content = result["element"].text_all
        return {"text": content if content else ""}
    return {"text": None, "error": "Element not found"}


async def find_element_info(
    tab: nodriver.Tab,
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
        all_elements: If True, find all matching elements
        timeout: Search timeout in seconds

    Returns:
        dict with found, count (if all), tag, text (for single element)
    """
    if all_elements:
        result = await find_elements(tab, text=text, selector=selector, timeout=timeout)
        return {
            "found": result["count"] > 0,
            "count": result["count"],
        }
    else:
        result = await find_element(tab, text=text, selector=selector, timeout=timeout)
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


async def wait_for_element_with_info(
    tab: nodriver.Tab,
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
    result = await wait_for_element(tab, text=text, selector=selector, timeout=timeout)

    # Add descriptive message
    if result.get("found"):
        if text:
            result["message"] = f"Element with text '{text}' found"
        else:
            result["message"] = f"Element '{selector}' found"
    else:
        result["message"] = f"Timeout after {timeout}s"

    return result


async def click_text(
    tab: nodriver.Tab,
    text: str,
    timeout: float = 10,
    human_like: bool = True,
) -> dict:
    """Click element by text content.

    This is the primary way for AI to click elements. Use find() first to
    see available elements, then click_text with the exact text.

    Args:
        tab: Tab instance
        text: Text content of the element to click
        timeout: Search timeout in seconds
        human_like: Use CDP events (default True, recommended)

    Returns:
        dict with clicked status

    Example:
        click_text("登录")
        click_text("Sign in")
        click_text("Submit", timeout=5)
    """
    result = await click(tab, text=text, timeout=timeout, human_like=human_like)
    return {"clicked": result, "text": text}
