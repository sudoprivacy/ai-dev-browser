"""Element interaction operations."""

import asyncio
import json


from ai_dev_browser.cdp import input_ as cdp_input

from . import human
from ._element import Element
from ._ref import make_ref
from ._tab import Tab
from .ax import _type_keystrokes, click_by_ref, get_element_by_ref, press_key
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


# Find-and-scroll-the-real-scroller JS, run for to_bottom / to_top.
#
# `window.scrollTo` on the top document is wrong the moment the page's
# scrollable content lives somewhere else — a nested `overflow:auto`
# pane or a same-origin iframe (e.g. a doc viewer that embeds the body
# in an <iframe>). The top window then has nothing to scroll and the
# command is a silent no-op. This walks the top document AND every
# reachable same-origin frame, collects the genuinely-scrollable
# containers, scrolls the right one to the requested edge, and reports
# what it did so the caller can fail loud when nothing was scrollable.
#
# `__DIR__` is substituted with the literal 'bottom' or 'top' (never
# user input — no injection surface).
_SCROLL_TO_EDGE_JS = r"""(() => {
  const DIR = '__DIR__';
  const MIN = 4;  // scrollHeight - clientHeight must exceed this to count

  const roomOf = (el) => el.scrollHeight - el.clientHeight;

  const describe = (el, win, root) => {
    if (el === root) return win === window ? 'window' : 'frame-document';
    const id = el.id ? '#' + el.id : '';
    const cls = (typeof el.className === 'string' && el.className.trim())
      ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '';
    return (el.tagName || 'node').toLowerCase() + id + cls;
  };

  const candidates = [];
  let crossOrigin = false;

  const collect = (win, prefix) => {
    let doc;
    try { doc = win.document; } catch (e) { crossOrigin = true; return; }
    if (!doc) return;
    const root = doc.scrollingElement || doc.documentElement || doc.body;
    if (root && roomOf(root) > MIN) {
      candidates.push({ el: root, win, room: roomOf(root),
                        label: prefix + describe(root, win, root), top: prefix === '' });
    }
    for (const el of doc.querySelectorAll('*')) {
      if (el === root || roomOf(el) <= MIN) continue;
      const oy = win.getComputedStyle(el).overflowY;
      if (oy === 'auto' || oy === 'scroll' || oy === 'overlay') {
        candidates.push({ el, win, room: roomOf(el),
                          label: prefix + describe(el, win, root), top: false });
      }
    }
    for (const frame of doc.querySelectorAll('iframe, frame')) {
      let cw;
      try { cw = frame.contentWindow; if (cw) void cw.document; }
      catch (e) { crossOrigin = true; continue; }
      if (!cw) continue;
      const tag = frame.id ? '#' + frame.id
                  : (frame.name ? '[name=' + frame.name + ']' : '');
      collect(cw, prefix + 'iframe' + tag + ' > ');
    }
  };

  collect(window, '');
  if (candidates.length === 0) return { found: false, crossOrigin };

  // "Scroll the page" means the top window when it can scroll; only when
  // the page itself is not scrollable do we hunt for the embedded scroller
  // (pick the one with the most room — the doc-viewer iframe, not a stray
  // 10px widget).
  let t = candidates.find((c) => c.top);
  if (!t) t = candidates.reduce((a, b) => (b.room > a.room ? b : a));

  const el = t.el;
  const before = el.scrollTop;
  el.scrollTop = DIR === 'bottom' ? el.scrollHeight : 0;
  return {
    found: true, target: t.label, before, after: el.scrollTop,
    delta: el.scrollTop - before, crossOrigin, candidates: candidates.length,
  };
})()"""


async def _scroll_to_edge(tab: Tab, edge: str) -> dict:
    """Scroll the real scroll container (top window, nested pane, or
    same-origin iframe) to `edge` ('bottom' | 'top'). Returns the JS
    diagnostics dict (`found`, `target`, `delta`, `crossOrigin`, ...)."""
    return await tab.evaluate(_SCROLL_TO_EDGE_JS.replace("__DIR__", edge))


async def _resolve_scroll_target(tab: Tab, target: Element | str) -> Element | None:
    """Turn a `to_element` value into an Element. A string is looked up
    the same way the `*_by_text` tools locate things — accessible name
    first (spans same-origin iframes), then a raw text-node search — so
    scrolling to a landmark agrees with clicking/finding it. An Element
    is returned unchanged."""
    if not isinstance(target, str):
        return target
    hit = await _ax_by_text(tab, target)
    if hit and hit.get("ref"):
        try:
            return await get_element_by_ref(tab, hit["ref"])
        except Exception:
            pass
    return await tab.find(target, timeout=3)


async def page_scroll(
    tab: Tab,
    direction: str = "down",
    amount: int = 25,
    to_bottom: bool = False,
    to_top: bool = False,
    to_element: Element | str | None = None,
) -> dict:
    """Use when: the target element isn't in the viewport — lazy-loaded
    content, infinite scroll feed, or a long form. Returns
    `{scrolled: True, target, ...}` on success, or
    `{scrolled: False, reason}` when nothing moved. Follow-ups:
    `page_discover` to see newly-rendered items, or a direct
    `click_by_*` / `find_by_*` if you know the locator.

    `to_element` accepts the element's visible text (or an `Element`) and
    scrolls it into view — resolved via the same accessible-name locator
    as `find_by_text`, so it reaches targets inside same-origin iframes.

    `to_bottom` / `to_top` scroll the *actually* scrollable container, not
    just the top window: a page whose body is embedded in an
    `overflow:auto` pane or a same-origin iframe (doc viewers, editors)
    is scrolled correctly, and `target` names what was scrolled. If the
    page has nothing scrollable, `scrolled` is False with a `reason`
    instead of a false success.

    Args:
        tab: Tab instance
        direction: "up" or "down" (incremental gesture scroll)
        amount: Scroll amount (percentage of viewport) for direction scroll
        to_bottom: Scroll the scrollable container to its bottom
        to_top: Scroll the scrollable container to its top
        to_element: Visible text (or an Element) to scroll into view

    Returns:
        dict — `{scrolled: True, target, ...}` on success;
        `{scrolled: False, reason}` when nothing was scrollable.

    Failure:
        `scrolled: false` means nothing moved. `reason` says why: no
        element matched `to_element` (check the text with `page_discover`),
        the page has no scrollable content, or the content lives in a
        cross-origin iframe JS scroll can't reach — for that case try
        `direction='down'` (gesture scroll routes to whatever is under the
        cursor), or scroll it directly with `js_evaluate(frame=...)`. When
        `to_bottom`/`to_top` succeed, the `target`
        field names the container that was scrolled; if it picked the
        wrong one, scroll that element by text via `to_element` instead.
    """
    if to_element is not None:
        element = await _resolve_scroll_target(tab, to_element)
        if element is None:
            return {
                "scrolled": False,
                "reason": f"no element found to scroll to for {to_element!r}",
            }
        await element.scroll_into_view()
        return {
            "scrolled": True,
            "target": to_element if isinstance(to_element, str) else repr(element),
        }

    if to_bottom or to_top:
        info = await _scroll_to_edge(tab, "bottom" if to_bottom else "top")
        if not info.get("found"):
            if info.get("crossOrigin"):
                reason = (
                    "the scrollable content is inside a cross-origin iframe that "
                    "this JS scroll can't reach; try direction='down' (gesture "
                    "scroll routes to whatever is under the cursor), or scroll it "
                    "directly with js_evaluate(frame=...)"
                )
            else:
                reason = (
                    "nothing on this page is scrollable (content fits the viewport)"
                )
            return {"scrolled": False, "reason": reason}
        return {
            "scrolled": True,
            "target": info.get("target"),
            "y": info.get("after"),
            "delta": info.get("delta"),
        }

    # Incremental scroll keeps the gesture path (Browser.getWindow +
    # Input.synthesizeScrollGesture, JS-scrollBy fallback on embedded
    # targets) — its gesture-shape acceleration matters for anti-bot
    # heuristics, so it is deliberately not routed through the JS scroller.
    if direction == "up":
        await tab.scroll_up(amount)
    else:
        await tab.scroll_down(amount)
    return {"scrolled": True, "direction": direction, "amount": amount}


# Cheap presence+visibility probe for the wait loop: resolve the target by CSS
# `selector` or visible `text` and report whether it's rendered + its rect — in
# ONE `querySelector` / text-walk, with NO `DOM.getDocument`. Polling the full
# pierced document every tick is what made page_wait_element crawl to minutes on
# heavy pages (an ERP console can carry 3800+ actionable nodes). An element in
# the DOM can still be unusable — 0-size, display:none, visibility:hidden (a
# search box mounted collapsed until its panel opens is the classic SPA trap) —
# so presence alone returns too early; this checks it's really visible. The
# backend node id for the ref is resolved ONCE, only after it's stably visible.
_WAIT_PROBE_JS = r"""(function (selector, text) {
  var el = null, idx = -1;
  var vis = function (e) {
    var r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return r.width > 2 && r.height > 2 &&
           s.visibility !== 'hidden' && s.display !== 'none';
  };
  if (selector) {
    // First VISIBLE match, not just the first match — a menu/grid can have
    // many same-class nodes where the leading ones are collapsed.
    var els = document.querySelectorAll(selector);
    for (var i = 0; i < els.length; i++) {
      if (vis(els[i])) { el = els[i]; idx = i; break; }
    }
  } else if (text) {
    var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
    var n;
    while ((n = w.nextNode())) {
      if ((n.nodeValue || '').indexOf(text) !== -1) {
        var p = n.parentElement;
        if (p && vis(p)) { el = p; break; }
      }
    }
  }
  if (!el) return null;
  var r = el.getBoundingClientRect();
  return {
    idx: idx,
    left: Math.round(r.left), top: Math.round(r.top),
    right: Math.round(r.right), bottom: Math.round(r.bottom),
  };
})(__SELECTOR__, __TEXT__)"""


async def _wait_probe(tab: Tab, text: str | None, selector: str | None) -> dict | None:
    """One cheap shot (no getDocument): the first VISIBLE `selector`/`text`
    match's `{idx, left, top, right, bottom}`, or None if none is visible."""
    js = _WAIT_PROBE_JS.replace(
        "__SELECTOR__", json.dumps(selector) if selector else "null"
    ).replace("__TEXT__", json.dumps(text) if text else "null")
    try:
        return await tab.evaluate(js)
    except Exception:
        return None


async def _resolve_ref(
    tab: Tab, text: str | None, selector: str | None, idx: int
) -> tuple[str, str, str | None] | None:
    """Resolve the located element to `(ref, role, name)` — the one
    `DOM.getDocument`, run once the element is confirmed stably visible. `idx`
    picks the same (first-visible) match the probe chose."""
    if selector:
        elements = await tab.query_selector_all(selector)
        if not elements:
            return None
        element = elements[idx] if 0 <= idx < len(elements) else elements[0]
    elif text:
        element = await tab.find_element_by_text(text)
    else:
        element = None
    if element is None:
        return None
    return (
        make_ref(1, int(element.backend_node_id)),
        (element.node_name or "").lower(),
        (element.text_all or "").strip()[:80] or None,
    )


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
    """Use when: an element appears **asynchronously after an action** — you
    click a menu and its panel/input renders, open a modal, a suggestion list
    drops, a tab swaps in a new panel — and you must wait for it to be usable
    before acting. This is the fix for the `mouse_click` → `sleep` → re-discover
    dance: `click_* → page_wait_element(selector=…) → type_by_ref(ref)`.

    Returns `{found, ref, role, name, x, y, box, elapsed}` — feed `ref`
    STRAIGHT into `type_by_ref` / `click_by_ref` / `focus_by_ref`, no
    intermediate `page_discover`.

    Waits for the element to be **visible**, not merely present: a control
    that's mounted collapsed (0-size / `display:none` / `visibility:hidden`
    until its panel opens — very common in SPAs/ERPs) is skipped until it
    actually renders. It must stay visible across two polls before its `ref` is
    resolved, so a node caught mid-remount isn't handed back. When several
    elements match, the first **visible** one wins (a 63-link menu where the
    leading links are collapsed). Locate ARIA-less controls by CSS `selector`
    (`input[datarole=x]`, `[placeholder*=智能]`, `.kd-foo`); `text` matches
    visible text in the top frame.

    Args:
        tab: Tab instance
        text: Visible text to wait for
        selector: CSS selector to wait for (use this for ARIA-less / datarole
            controls, or anything without visible text)
        timeout: Maximum wait time in seconds

    Returns:
        dict `{found: True, ref, role, name, x, y, box, elapsed}` once the
        element is visible, or `{found: False, elapsed, message}` on timeout.

    Failure:
        The element never became visible within `timeout`. It may be present
        but still collapsed (its trigger action may not have opened its panel
        yet — re-do the click, or raise `timeout`); the locator may be wrong
        (check with `page_discover`, try a broader `selector` / partial
        `text`); or it's in a cross-origin iframe (probe it with
        `js_evaluate(frame="<url-substr>")`). A `text` locator scans the top
        frame only — prefer a CSS `selector` for iframe/ARIA-less targets.
    """
    loop = asyncio.get_running_loop()
    start = loop.time()
    was_visible = False
    while True:
        probe = await _wait_probe(tab, text, selector)
        if probe is not None:
            # Require visible on two consecutive polls before resolving the ref,
            # so a node caught mid-remount (stale for type_by_ref) isn't handed
            # back. The ref costs one DOM.getDocument — paid once, here.
            if was_visible:
                resolved = await _resolve_ref(tab, text, selector, probe["idx"])
                if resolved is not None:
                    ref, role, name = resolved
                    return {
                        "found": True,
                        "ref": ref,
                        "role": role,
                        "name": name,
                        "x": round((probe["left"] + probe["right"]) / 2),
                        "y": round((probe["top"] + probe["bottom"]) / 2),
                        "box": {
                            "left": probe["left"],
                            "top": probe["top"],
                            "right": probe["right"],
                            "bottom": probe["bottom"],
                        },
                        "elapsed": round(loop.time() - start, 2),
                    }
            was_visible = True
        else:
            was_visible = False

        if loop.time() - start > timeout:
            return {
                "found": False,
                "elapsed": round(loop.time() - start, 2),
                "message": f"Timeout after {timeout}s (not visible)",
            }
        await asyncio.sleep(0.3)


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
        not scanned — reach into one with `js_evaluate(frame="<url-substr>")`.

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


# Locate a grid ROW by its text, then act on it — for grids (Kingdee K3Cloud
# F7 pick-lists / authorization tables) where estimating coordinates from a
# screenshot mis-clicks the neighbouring row. One row-finder, three modes:
#   "row"      -> the row's centre (click / double-click the row)
#   "checkbox" -> the clickable target of the row's checkbox
#   "verify"   -> read the row checkbox's checked state (post-click)
#
# The checkbox target is the widget that actually toggles: many frameworks
# (Kingdee `<input onclick="return false">`, MUI, AntD, Element UI) lock or
# hide the real `<input>` and route the click through a wrapper `<div>` / label,
# so clicking the input does nothing. This prefers the visible wrapper.
_FIND_ROW_JS = r"""(function (needle, nth, mode) {
  const cand = Array.prototype.slice
    .call(document.querySelectorAll('[class*=row],[role=row],tr'))
    .filter(function (el) { return (el.innerText || '').indexOf(needle) !== -1; })
    .filter(function (el) {
      // Rendered (has size). Deliberately NOT limited to the current viewport:
      // a row scrolled out of a long F7 list is a valid target — scrollTo below
      // brings it in before we click.
      const r = el.getBoundingClientRect();
      return r.width > 20 && r.height > 2;
    });
  const set = new Set(cand);
  // Keep only the outermost matching row (a grid row can nest sub-rows).
  const outer = cand.filter(function (el) {
    let p = el.parentElement;
    while (p) { if (set.has(p)) return false; p = p.parentElement; }
    return true;
  });
  const row = outer[nth];
  if (!row) return null;
  const vis = function (el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return r.width > 2 && r.height > 2;
  };
  const scrollTo = function (el) {
    // Bring the target into the scroll viewport BEFORE measuring — a row (or
    // its checkbox) scrolled out of a long F7 list has off-screen coords, so
    // clicking them lands nowhere / on the wrong row (silent checked:false).
    try {
      if (el.scrollIntoViewIfNeeded) el.scrollIntoViewIfNeeded(true);
      else el.scrollIntoView({ block: 'center', inline: 'nearest' });
    } catch (e) {}
  };
  const cb = row.querySelector('input[type=checkbox],input[type=radio]');

  if (mode === 'verify') {
    return { checked: cb ? !!cb.checked : null,
             ariaSelected: row.getAttribute('aria-selected') };
  }

  const info = {
    matches: outer.length,
    text: (row.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 80),
  };

  if (mode !== 'checkbox') {
    scrollTo(row);
    const r = row.getBoundingClientRect();
    info.x = Math.round(r.left + r.width / 2);
    info.y = Math.round(r.top + r.height / 2);
    return info;
  }

  // checkbox mode — click the widget that actually handles the toggle.
  let target = null;
  const roleCb = row.querySelector(
    '[role=checkbox],[data-role=checkbox],[datarole=checkbox]');
  if (cb) {
    info.checkedBefore = !!cb.checked;
    let wrapper = null, n = cb;
    for (let i = 0; i < 5 && n; i++) {
      n = n.parentElement;
      if (!n || n === row) break;
      if (n.matches('[role=checkbox],[data-role=checkbox],[datarole=checkbox]') ||
          /check|switch|toggle/i.test(n.className || '')) { wrapper = n; break; }
    }
    let label = null;
    try {
      label = cb.id
        ? row.querySelector('label[for="' +
            (window.CSS && CSS.escape ? CSS.escape(cb.id) : cb.id) + '"]')
        : cb.closest('label');
    } catch (e) {}
    const locked = cb.hasAttribute('onclick');   // e.g. onclick="return false"
    target = (locked && vis(wrapper)) ? wrapper
      : (vis(cb) ? cb : (vis(wrapper) ? wrapper : (vis(label) ? label
      : (wrapper || cb))));
  } else if (roleCb) {
    target = roleCb;
    info.checkedBefore = roleCb.getAttribute('aria-checked') === 'true';
  }
  if (!target) { info.nocheckbox = true; return info; }
  scrollTo(target);
  const tr = target.getBoundingClientRect();
  info.x = Math.round(tr.left + tr.width / 2);
  info.y = Math.round(tr.top + tr.height / 2);
  return info;
})(__NEEDLE__, __NTH__, __MODE__)"""


async def click_row_by_text(
    tab: Tab,
    text: str,
    double: bool = False,
    nth: int = 0,
    checkbox: bool = False,
) -> dict:
    """Use when: you need to act on a row in a **grid table** by its visible
    text — click it, double-click it, or **toggle its checkbox** — and
    `page_discover` / `click_by_text` can't reliably (grids whose rows are bare
    `div[class*=row]`: Kingdee K3Cloud F7 pick-lists, authorization tables).
    Locates the row that actually *contains* `text` and acts on its exact
    target, so it can't drift onto the neighbour an estimated
    `mouse_click --x --y` would hit. The row is **scrolled into view first**,
    so a row far down a long F7 list is reached without any manual scrolling.

    Returns `{clicked, text, matches, x, y}` — `text` is the row it actually
    hit (confirm it's the one you meant) and `matches` how many rows contained
    the text (if >1, disambiguate with `nth`).

    `checkbox=True` toggles the row's **checkbox** instead of clicking the row,
    and clicks the element that actually handles the toggle — many grids
    (Kingdee `<input onclick="return false">`, MUI, AntD) lock or hide the real
    `<input>` and route the click through a wrapper `<div>`/label, so clicking
    the input is a no-op. The return adds `{was, checked}` (the checkbox state
    before/after, read back from the DOM) so you can confirm the toggle took
    without a second call. `double=True` double-clicks the row ("double-click
    to choose" in F7 dialogs); ignored when `checkbox=True`.

    For a normally-labelled control prefer `click_by_text`; this is for
    ref-less grid rows and their locked/wrapped checkboxes.

    Args:
        tab: Tab instance
        text: Text the target row contains (substring)
        double: Double-click the row instead of single-click
        nth: 0-based index when several rows match the text
        checkbox: Toggle the row's checkbox (via its real clickable target)
            instead of clicking the row

    Returns:
        dict `{clicked: True, text, matches, x, y}` (+ `double`), or for
        `checkbox=True` `{clicked: True, text, matches, x, y, was, checked}`
        where `checked` is the verified post-click state. `{clicked: False,
        reason}` when no row contains the text (or it has no checkbox).

    Failure:
        No grid row contained the text — check spelling, try a shorter unique
        substring, confirm the grid is rendered (`page_screenshot`), or the
        control isn't a grid row (use `find_by_text` + `click_by_ref`, or
        `click_by_text`). With `checkbox=True`, the matched row may simply have
        no checkbox — `reason` says so.
    """

    def _row_js(mode: str) -> str:
        return (
            _FIND_ROW_JS.replace("__NEEDLE__", json.dumps(text))
            .replace("__NTH__", str(int(nth)))
            .replace("__MODE__", json.dumps(mode))
        )

    hit = await tab.evaluate(_row_js("checkbox" if checkbox else "row"))
    if not hit:
        return {"clicked": False, "reason": f"no grid row containing {text!r}"}
    if checkbox and hit.get("nocheckbox"):
        return {"clicked": False, "reason": f"row {hit.get('text')!r} has no checkbox"}

    x, y = hit["x"], hit["y"]
    if double and not checkbox:
        # Two press/release pairs, the second with click_count=2, so a real
        # `dblclick` fires (a plain double mouse_click doesn't).
        btn = cdp_input.MouseButton("left")
        for count in (1, 2):
            await tab.send(
                cdp_input.dispatch_mouse_event(
                    "mousePressed", x=x, y=y, button=btn, click_count=count
                )
            )
            await tab.send(
                cdp_input.dispatch_mouse_event(
                    "mouseReleased", x=x, y=y, button=btn, click_count=count
                )
            )
    else:
        await tab.mouse_click(x, y)

    result = {
        "clicked": True,
        "text": hit.get("text"),
        "matches": hit.get("matches"),
        "x": x,
        "y": y,
    }
    if checkbox:
        # Read the checkbox state back so the caller can confirm the toggle
        # took — the whole point, since clicking a locked <input> wouldn't.
        await tab.sleep(0.15)
        after = await tab.evaluate(_row_js("verify"))
        result["was"] = hit.get("checkedBefore")
        result["checked"] = (after or {}).get("checked")
    else:
        result["double"] = double
    return result


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
        text filter. Cross-origin iframes are not scanned — reach into one
        with `js_evaluate(frame="<url-substr>")`.
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
    enter: bool = False,
    keystrokes: bool = False,
) -> dict:
    """Use when: you know an input's visible label / placeholder / accessible
    name (e.g. "Email", "Search…"). Locates by AX name + types. Returns
    `{typed, name}` (plus `entered` when `enter=True`).

    Prefer over `type_by_ref` when you can identify the input by its
    human-visible label rather than needing a prior `page_discover` ref. The
    `clear` / `enter` / `keystrokes` / `human_like` options mirror `type_by_ref`
    so the two are interchangeable once the input is located.

    Set `enter=True` to press Enter after typing (submit a search). The typing
    mechanism defaults to per-character `char` events; `keystrokes=True` sends
    real key events for fields that ignore a bulk change (live filters /
    autocomplete), and `human_like` adds human timing — `keystrokes` wins if
    both are set.

    Args:
        tab: Tab instance
        name: Accessible name to page_discover element (placeholder, label, etc.)
        text: Text to type into the element
        clear: If True, clear existing content first
        timeout: Search timeout in seconds
        human_like: Add human timing between keystrokes (default: from config)
        enter: If True, press Enter after typing (submits the field)
        keystrokes: If True, send real per-character key events (for live
            filters / autocomplete)

    Returns:
        dict with typed status; includes `entered` when `enter=True`

    Failure:
        No input with this accessible name, in the main frame or any same-origin
        iframe, within `timeout`. If the input has no accessible name at all
        (no label, no placeholder, no aria-label), locate it by html id or xpath
        instead: `find_by_html_id` / `find_by_xpath` → `type_by_ref`.
        Cross-origin iframes are not scanned — type into one with
        `js_evaluate(frame="<url-substr>", "el.value = ...")`.

    Example:
        type_by_text(name="用户名", text="myusername")
        type_by_text(name="Search", text="query", clear=True, enter=True)
        type_by_text(name="快捷过滤", text="FIN", keystrokes=True)  # live filter
    """
    # Locator only — same accessible-name lookup as click_by_text / find_by_text.
    # Locating by AX name is what this tool has always *claimed* to do; it was
    # running a DOM text-node search, so a `<label for=email>Email</label>` match
    # landed on the label instead of the input it labels.
    #
    # The DEFAULT typing actuator is deliberately per-character `char` events
    # (not `type_by_ref`'s `Input.insertText`) — the two produce different DOM
    # event streams and routing one through the other silently changes which
    # pages work. `keystrokes=True` is the explicit shared opt-in (real key
    # events, same `_type_keystrokes` path as `type_by_ref`) for the fields that
    # need it; it does not change the default.
    located = await _wait_ax_by_text(tab, name, timeout)
    if located is None:
        return {"typed": False, "error": f"Element with name '{name}' not found"}

    element = await get_element_by_ref(tab, located["ref"])
    if element is None:
        return {"typed": False, "error": f"Element with name '{name}' not found"}

    if clear:
        await element.clear_input()

    if keystrokes:
        await element.focus()  # keys land on the focused element
        await _type_keystrokes(tab, text)
    else:
        use_human = (
            human_like if human_like is not None else human.get_config().type_humanize
        )
        if use_human:
            await human.type_text(tab, text, element, humanize=True)
        else:
            await element.send_keys(text)

    result = {"typed": True, "name": name, "ref": located["ref"]}
    if enter:
        pressed = await press_key(tab, "Enter", ref=located["ref"])
        result["entered"] = bool(pressed.get("pressed"))
    return result


# JS that selects a text range in the top document or the first same-origin
# frame that contains the text, then fires the tail of a real selection
# gesture. Kept as one expression (IIFE) so tab.evaluate gets a single value.
#
# Why this exists as a primitive and not a coordinate drag: a
# DevTools-synthesized mouse drag does not drive Blink's cross-frame text
# selection state machine — the events reach an iframe's JS listeners but no
# Selection is populated, and a same-origin iframe has no separate CDP target
# to route frame-local input to. Building the Range directly in the correct
# document is the deterministic path that actually works.
_SELECT_TEXT_JS = """
    (function(startText, endText) {
      function findRange(doc) {
        const root = doc.body || doc.documentElement;
        if (!root) return null;
        const walk = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
        let startNode = null, startOff = -1;
        while (walk.nextNode()) {
          const tn = walk.currentNode;
          const i = (tn.nodeValue || '').indexOf(startText);
          if (i >= 0) { startNode = tn; startOff = i; break; }
        }
        if (!startNode) return null;
        const rg = doc.createRange();
        rg.setStart(startNode, startOff);
        if (endText) {
          // Extend to the first endText at or after the start node, so the
          // selection can span formatting boundaries / multiple elements.
          const walk2 = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
          let seen = false, endNode = null, endOff = -1;
          while (walk2.nextNode()) {
            const tn = walk2.currentNode;
            if (tn === startNode) seen = true;
            if (!seen) continue;
            const from = (tn === startNode) ? startOff : 0;
            const j = (tn.nodeValue || '').indexOf(endText, from);
            if (j >= 0) { endNode = tn; endOff = j + endText.length; break; }
          }
          if (!endNode) return null;
          rg.setEnd(endNode, endOff);
        } else {
          rg.setEnd(startNode, startOff + startText.length);
        }
        return rg;
      }
      function recurse(win, ctx) {
        let doc;
        try { doc = win.document; } catch (e) { return null; }  // cross-origin
        let rg = null;
        try { rg = findRange(doc); } catch (e) { rg = null; }
        if (rg) return { win: win, doc: doc, rg: rg, ctx: ctx };
        for (let i = 0; i < win.frames.length; i++) {
          try {
            const hit = recurse(win.frames[i], 'iframe');
            if (hit) return hit;
          } catch (e) {}
        }
        return null;
      }
      const hit = recurse(window, 'top');
      if (!hit) return { selected: false, text: startText };
      const win = hit.win, doc = hit.doc, rg = hit.rg;
      const sel = win.getSelection();
      sel.removeAllRanges();
      sel.addRange(rg);
      const out = sel.toString();
      const collapsed = sel.isCollapsed;
      const ok = sel.rangeCount > 0 && !collapsed && out.length > 0;
      // Notify selection listeners. Only `selectionchange` — the platform's own
      // signal for a selection change — is fired. A synthetic `mouseup` is
      // deliberately NOT dispatched: on real pages a mouseup handler routinely
      // clears the selection (an untrusted synthetic mouseup can't finalize a
      // native gesture anyway), which would wipe the very selection we just
      // made. Callers wanting a trusted pointer event drive it separately.
      try { doc.dispatchEvent(new win.Event('selectionchange')); } catch (e) {}
      return {
        selected: ok, text: out, query: startText, frame: hit.ctx,
        chars: out.length, collapsed: collapsed
      };
    })(%s, %s)
"""


async def select_text(tab: Tab, text: str, to_text: str | None = None) -> dict:
    """Use when: you need a real text *selection* (highlight) over on-page text
    — to drive a select-to-comment / annotate / quote widget, or anything that
    reads `window.getSelection()`. Returns `{selected, text, frame, chars}`;
    `selected` + `text` already confirm what got highlighted, so there's no need
    to screenshot or re-read the selection to check.

    Works in the top document AND same-origin iframes (it recurses frames the
    way `find_by_xpath` does). This is the capability `mouse_drag` lacks: a
    synthetic coordinate drag doesn't drive the browser's cross-frame selection
    state machine, so dragging over iframe text selects nothing. Locate by the
    text itself, not pixels — the frame and character offsets are resolved for
    you.

    Selects the first occurrence of `text` within a single text node. For a run
    that spans formatting boundaries (a bold word, a link) or several elements,
    pass `to_text`: the selection runs from the start of `text` to the end of
    the first `to_text` at or after it — the text equivalent of a click-drag
    from one point to another.

    The selection is real and persists; the only event fired is
    `selectionchange` (the platform's selection signal). It does not simulate a
    pointer gesture — a widget that reacts solely to a trusted `mouseup` won't
    fire from this alone (drive that separately, e.g. with `mouse_click`).

    Not for native `<select>` dropdowns — that's `select_by_ref` (which picks an
    `<option>`). This selects arbitrary rendered text.

    Args:
        tab: Tab instance
        text: Visible text to select, matched as a substring within one text
            node. Case-sensitive against the rendered text.
        to_text: Optional. When given, the selection extends to the end of the
            first occurrence of this text at or after `text`, spanning any
            elements in between. Use for multi-node / multi-element runs.

    Returns:
        dict: on success `{selected: True, text, query, frame, chars,
        collapsed: False}`, where `text` is the actual
        `getSelection().toString()` (may differ from the query — e.g. CSS
        `text-transform` renders it upper-case) and `frame` is `"top"` or
        `"iframe"`. On miss `{selected: False, text: <query>}`.

    Failure:
        Text not found in the main frame or any same-origin iframe (or, with
        `to_text`, no `to_text` at/after `text`). The match is a case-sensitive
        substring *within a single text node* — if the run spans elements,
        select a shorter substring that lives in one node, or pass `to_text` for
        the span. Confirm the text is present with `find_by_text` / `page_html`.
        Cross-origin iframe text isn't reachable by this tool — build the
        selection inside the frame with `js_evaluate(frame="<url-substr>")`
        (createRange + getSelection).

    Example:
        select_text("Term Sheet")
        select_text("除本意向书", to_text="明确允许")
    """
    expr = _SELECT_TEXT_JS % (
        json.dumps(text),
        json.dumps(to_text) if to_text else "null",
    )
    return await tab.evaluate(expr)


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
