"""AI-friendly page snapshot using accessibility tree."""

import re

from ai_dev_browser.cdp import accessibility
from ai_dev_browser.cdp import dom
from ai_dev_browser.cdp import page

from ._element import filter_recurse_all
from ._ref import make_ref, node_id_of
from ._tab import Tab


# DOM-based discovery. The AX-tree snapshot only sees elements the browser
# gives a role — useless on enterprise apps (Kingdee K3Cloud etc.) that build
# controls from bare `<div class="kd-*">` + custom `datarole="..."` attributes
# with NO standard ARIA. `getFullAXTree` returns a fraction of the real
# controls, so `page_discover` handed back too few refs and the agent was
# forced to guess click coordinates. This walks the real DOM for actionable
# nodes and returns each as an AX-shaped dict (ref + bbox + text label).
#
# Read-only by construction: reads `DOM.getDocument` + `DOM.getBoxModel` and
# NEVER mutates the page — tagging nodes to resolve refs would trip the grid's
# MutationObservers, so refs come from the pierced-document walk instead.
_ACTIONABLE_TAGS = {"input", "textarea", "select", "button", "a"}
_ACTIONABLE_ATTRS = ("onclick", "datarole", "role", "tabindex", "contenteditable")
_ACTIONABLE_CLASS = re.compile(r"cell|row|grid|kd-|k-icon", re.IGNORECASE)


def _node_attr(node, name: str) -> str | None:
    """Read one attribute value from a CDP DOM.Node's flat [n, v, n, v] list."""
    attrs = getattr(node, "attributes", None) or []
    for i in range(0, len(attrs) - 1, 2):
        if attrs[i] == name:
            return attrs[i + 1]
    return None


def _is_actionable(node) -> bool:
    """A node the user could click / type into — by tag, by an interaction
    attribute, or by a grid/widget class (the ARIA-less K3Cloud pattern)."""
    if (getattr(node, "node_name", "") or "").lower() in _ACTIONABLE_TAGS:
        return True
    if any(_node_attr(node, a) is not None for a in _ACTIONABLE_ATTRS):
        return True
    return bool(_ACTIONABLE_CLASS.search(_node_attr(node, "class") or ""))


def _node_label(node) -> str:
    """Best-effort human label: an interaction attribute if present, else the
    node's own text (grid rows carry their text, not an attribute)."""
    for attr in ("aria-label", "placeholder", "value", "title", "datarole"):
        val = _node_attr(node, attr)
        if val and val.strip():
            return val.strip()[:80]
    texts = [
        tn.node_value
        for tn in filter_recurse_all(node, lambda n: getattr(n, "node_type", 0) == 3)
        if getattr(tn, "node_value", None)
    ]
    joined = re.sub(r"\s+", " ", " ".join(texts)).strip()
    return joined[:80] if joined else (_node_attr(node, "name") or "").strip()[:80]


async def _dom_scan(tab: Tab, text: str | None = None, limit: int = 200) -> list[dict]:
    """Discover actionable elements straight from the DOM (not the AX tree).

    Read-only. Returns element dicts shaped like the AX ones — `ref`, `role`,
    `name`, `x`, `y`, `box` (+ `datarole` when present) — so callers can't tell
    which source a ref came from and `click_by_ref` / `type_by_ref` work
    uniformly. `text`, when given, filters by label substring BEFORE the
    per-node box-model round trip, so a text-scoped scan stays cheap.
    """
    doc = await tab.send(dom.get_document(-1, True))
    text_l = text.lower() if text else None

    results: list[dict] = []
    seen: set = set()
    for node in filter_recurse_all(doc, _is_actionable):
        if len(results) >= limit:
            break
        label = _node_label(node)
        if text_l and text_l not in label.lower():
            continue
        backend = getattr(node, "backend_node_id", None)
        if backend is None:
            continue
        try:
            box = await tab.send(
                dom.get_box_model(backend_node_id=dom.BackendNodeId(int(backend)))
            )
        except Exception:
            continue  # not rendered / detached — invisible, skip
        if not box or not box.content:
            continue
        q = box.content
        left, right = min(q[0], q[2], q[4], q[6]), max(q[0], q[2], q[4], q[6])
        top, bottom = min(q[1], q[3], q[5], q[7]), max(q[1], q[3], q[5], q[7])
        if right - left < 3 or bottom - top < 3:
            continue  # zero-size
        key = (round(left), round(top), round(right - left), round(bottom - top), label)
        if key in seen:  # drop container/child duplicates sharing rect + label
            continue
        seen.add(key)
        el = {
            "ref": make_ref(len(results) + 1, int(backend)),
            "role": _node_attr(node, "role")
            or _node_attr(node, "datarole")
            or (getattr(node, "node_name", "") or "").lower(),
            "name": label,
            "x": round((left + right) / 2),
            "y": round((top + bottom) / 2),
            "box": {
                "left": round(left),
                "top": round(top),
                "right": round(right),
                "bottom": round(bottom),
            },
        }
        datarole = _node_attr(node, "datarole")
        if datarole:
            el["datarole"] = datarole
        results.append(el)
    return results


def _format_ax_node(
    node,
    ref_counter: list,
    max_depth: int,
    current_depth: int = 0,
    interactable_only: bool = False,
) -> list[dict]:
    """Format an accessibility node into AI-friendly structure."""
    results: list[dict] = []

    if current_depth > max_depth:
        return results

    # Extract properties
    props = {}
    if hasattr(node, "properties") and node.properties:
        for prop in node.properties:
            if hasattr(prop, "name") and hasattr(prop, "value"):
                name = (
                    prop.name.value if hasattr(prop.name, "value") else str(prop.name)
                )
                val = prop.value.value if hasattr(prop.value, "value") else prop.value
                props[name] = val

    role = node.role.value if hasattr(node, "role") and node.role else None
    name = node.name.value if hasattr(node, "name") and node.name else None

    # Skip ignored nodes
    if role in ("none", "generic", "InlineTextBox", "LineBreak"):
        if hasattr(node, "children") and node.children:
            for child in node.children:
                results.extend(
                    _format_ax_node(
                        child,
                        ref_counter,
                        max_depth,
                        current_depth + 1,
                        interactable_only,
                    )
                )
        return results

    # Interactable roles
    interactable_roles = {
        "button",
        "link",
        "textbox",
        "checkbox",
        "radio",
        "combobox",
        "listbox",
        "option",
        "menuitem",
        "tab",
        "switch",
        "slider",
        "spinbutton",
        "searchbox",
        "menu",
        "menubar",
    }
    is_interactable = role in interactable_roles or props.get("focusable", False)

    # Skip non-interactable if filter is on
    if (
        interactable_only
        and not is_interactable
        and role not in ("heading", "image", "img", "alert")
    ):
        if hasattr(node, "children") and node.children:
            for child in node.children:
                results.extend(
                    _format_ax_node(
                        child,
                        ref_counter,
                        max_depth,
                        current_depth + 1,
                        interactable_only,
                    )
                )
        return results

    # Build node info
    if role and (name or is_interactable or role == "image"):
        ref_counter[0] += 1

        # Get node_id first so we can encode it in ref
        node_id = None
        if hasattr(node, "backend_dom_node_id") and node.backend_dom_node_id:
            node_id = node.backend_dom_node_id
            # Extract int from BackendNodeId
            try:
                node_id = int(node_id)
            except (TypeError, ValueError):
                node_id = None

        ref_str = make_ref(ref_counter[0], node_id)

        info = {
            "ref": ref_str,
            "role": role,
        }

        if name:
            # AX names/values are usually strings but a slider / spinbutton /
            # progress node reports a NUMBER — slicing that raised
            # "'int' object is not subscriptable" and aborted the whole
            # snapshot, so page_discover returned an error instead of refs
            # (fatal on ARIA-poor apps full of numeric inputs). Coerce first.
            info["name"] = str(name)[:100]

        if hasattr(node, "value") and node.value:
            raw = node.value.value if hasattr(node.value, "value") else node.value
            val = str(raw) if raw is not None else ""
            if val:
                info["value"] = val[:50]

        # States
        if props.get("focused"):
            info["focused"] = True
        if props.get("disabled"):
            info["disabled"] = True
        if props.get("required"):
            info["required"] = True
        if props.get("checked") is not None:
            info["checked"] = props["checked"]
        if props.get("selected"):
            info["selected"] = True
        if props.get("expanded") is not None:
            info["expanded"] = props["expanded"]

        if role == "heading" and props.get("level"):
            info["level"] = props["level"]

        results.append(info)

    # Process children
    if hasattr(node, "children") and node.children:
        for child in node.children:
            results.extend(
                _format_ax_node(
                    child, ref_counter, max_depth, current_depth + 1, interactable_only
                )
            )

    return results


async def _get_all_frames(tab) -> list[dict]:
    """Get all frames in the page."""
    try:
        result = await tab.send(page.get_frame_tree())
        frames = []

        def collect_frames(frame_tree, is_main=True):
            frame = frame_tree.frame
            frames.append(
                {
                    "id": frame.id_,
                    "url": frame.url,
                    "is_main": is_main,
                }
            )
            if frame_tree.child_frames:
                for child in frame_tree.child_frames:
                    collect_frames(child, is_main=False)

        collect_frames(result)
        return frames
    except Exception:
        return []


async def _get_frame_nodes(
    tab,
    frame_id: str | None,
    interactable_only: bool,
    max_depth: int,
    ref_prefix: str = "",
) -> list:
    """Get accessibility nodes for a specific frame."""
    frame = page.FrameId(frame_id) if frame_id else None
    result = await tab.send(accessibility.get_full_ax_tree(frame_id=frame))

    if not result:
        return []

    ax_nodes = result.nodes if hasattr(result, "nodes") else result
    if not ax_nodes:
        return []

    ref_counter = [0]
    nodes = []

    for node in ax_nodes:
        if hasattr(node, "role") and node.role:
            formatted = _format_ax_node(
                node,
                ref_counter,
                max_depth,
                interactable_only=interactable_only,
            )
            nodes.extend(formatted)

    # Add prefix to refs for non-main frames
    if ref_prefix:
        for n in nodes:
            n["ref"] = f"{ref_prefix}:{n['ref']}"

    # Remove duplicates within this frame
    seen_refs = set()
    unique_nodes = []
    for n in nodes:
        ref = n.get("ref")
        if ref not in seen_refs:
            seen_refs.add(ref)
            unique_nodes.append(n)

    return unique_nodes


async def _get_snapshot(
    tab: Tab,
    interactable_only: bool = False,
    max_depth: int = 10,
    frame_id: str | None = None,
    include_iframes: bool = True,
) -> list:
    """Get AI-friendly accessibility tree snapshot.

    This is the key AI feature - returns semantic page structure
    instead of raw HTML.

    Args:
        tab: Tab instance
        interactable_only: If True, only return buttons, links, inputs, etc.
        max_depth: Maximum tree depth to traverse
        frame_id: If specified, only get accessibility tree for this frame.
        include_iframes: If True (default), include all iframes in the result.
                         Iframe elements have refs like "FRAME_xxx:1".

    Returns:
        List of nodes with role, name, and state info.
        Main frame elements have simple refs: "1", "2", etc.
        Iframe elements have prefixed refs: "FRAME_ABC123:1", "FRAME_ABC123:2", etc.

    Example:
        [
            {"ref": "1", "role": "button", "name": "Sign in"},
            {"ref": "2", "role": "textbox", "name": "Email", "focused": True},
            {"ref": "FRAME_ABC123:1", "role": "button", "name": "Submit"},
        ]
    """
    # Enable accessibility domain
    await tab.send(accessibility.enable())

    # If specific frame requested, just get that frame
    if frame_id:
        return await _get_frame_nodes(
            tab, frame_id, interactable_only, max_depth, ref_prefix=""
        )

    # Get main frame nodes
    all_nodes = await _get_frame_nodes(
        tab, None, interactable_only, max_depth, ref_prefix=""
    )

    # If not including iframes, return just main frame
    if not include_iframes:
        return all_nodes

    # Get all frames and add iframe content
    frames = await _get_all_frames(tab)
    for frame in frames:
        if frame["is_main"]:
            continue  # Already got main frame

        # Skip about:blank (truly empty), but scan about:srcdoc which
        # holds the inline HTML of a `<iframe srcdoc="...">` — that's
        # real content agents need to reach.
        if frame["url"] == "about:blank":
            continue

        try:
            iframe_nodes = await _get_frame_nodes(
                tab,
                frame["id"],
                interactable_only,
                max_depth,
                ref_prefix=f"FRAME_{frame['id'][:8]}",  # Use first 8 chars of frame ID
            )
            all_nodes.extend(iframe_nodes)
        except Exception:
            # Some frames may not be accessible, skip them
            pass

    return all_nodes


async def page_discover(
    tab: Tab,
    text: str | None = None,
    interactable_only: bool = True,
    include_coordinates: bool = True,
    include_iframes: bool = True,
    dom_scan: bool = True,
    dom_limit: int = 200,
) -> list[dict]:
    """Use when: you DON'T know what's on the page yet — broad exploration
    of all interactable elements (including same-origin iframes; iframe
    elements get `FRAME_xxx:` prefix on their refs, so filter the
    returned list by prefix to narrow to one frame).

    Also surfaces **ARIA-less controls the accessibility tree can't see** —
    custom `datarole` inputs, `div[class*=row]` grid rows, `kd-*` widgets
    (enterprise apps / ERPs like Kingdee K3Cloud) — each with a real `ref` +
    `box`. So this is the tool to reach a control when `click_by_text` /
    `find_by_text` come up empty on a heavy JS app. For a ref-less grid ROW,
    `click_row_by_text` clicks it directly.

    Returns a **list** of element dicts you iterate directly
    (`for el in await page_discover(tab): ...`). Feed each `ref` into
    `click_by_ref` / `type_by_ref` / `focus_by_ref` and each `x`/`y`
    into `mouse_click`. Use `len(result)` if you need the count.

    Pass `text` to filter by label — cheapest and most precise on a huge
    page (an ERP grid can have thousands of nodes; the filter runs before the
    costly geometry pass). Skip this tool entirely when you already know a
    locator: go straight to `click_by_html_id` / `click_by_xpath` /
    `click_by_text` (one call, no intermediate ref catalog).

    Args:
        tab: Tab instance
        text: Optional text filter (case-insensitive substring match)
        interactable_only: If True (default), only return interactive elements
        include_coordinates: If True (default), include x/y coordinates
        include_iframes: If True (default), include iframe content
        dom_scan: If True (default), also scan the DOM for actionable elements
            the AX tree misses (ARIA-less `datarole` / `div` grids / `kd-*`).
            Read-only — never mutates the page. Turn off for pure-AX results.
        dom_limit: Max DOM-scanned elements to return (default 200); a `text`
            filter keeps a real scan far under this.

    Returns:
        list of element dicts, each containing:
        - ref: reference for click_ref (e.g., "5#214")
        - role: element role (button, link, textbox, etc.)
        - name: accessible name
        - x, y: center coordinates (if include_coordinates=True)
        - box: {left, top, right, bottom} (if include_coordinates=True)
        - datarole: value of a custom `datarole` attribute, when present

    Example:
        elements = await page_discover()               # All interactive elements
        for el in elements:                            # Iterate directly
            if "Sign in" in el.get("name", ""):
                await click_by_ref(tab, el["ref"])
        page_discover(text="登录")                     # Filter by label
    """
    from ai_dev_browser.cdp import dom

    # Get accessibility tree
    elements = await _get_snapshot(
        tab,
        interactable_only=interactable_only,
        include_iframes=include_iframes,
    )

    # Filter by text if specified
    if text:
        text_lower = text.lower()
        elements = [
            el for el in elements if text_lower in (el.get("name") or "").lower()
        ]

    # Add coordinates if requested
    if include_coordinates:
        for el in elements:
            node_id = node_id_of(el.get("ref", ""))

            if node_id:
                try:
                    backend_node_id = dom.BackendNodeId(node_id)
                    box = await tab.send(
                        dom.get_box_model(backend_node_id=backend_node_id)
                    )
                    if box and box.content:
                        quad = box.content
                        # Calculate center
                        x = (quad[0] + quad[2] + quad[4] + quad[6]) / 4
                        y = (quad[1] + quad[3] + quad[5] + quad[7]) / 4
                        el["x"] = round(x)
                        el["y"] = round(y)
                        # Calculate bounding box
                        left = min(quad[0], quad[2], quad[4], quad[6])
                        top = min(quad[1], quad[3], quad[5], quad[7])
                        right = max(quad[0], quad[2], quad[4], quad[6])
                        bottom = max(quad[1], quad[3], quad[5], quad[7])
                        el["box"] = {
                            "left": round(left),
                            "top": round(top),
                            "right": round(right),
                            "bottom": round(bottom),
                        }
                except Exception:
                    # Skip coordinates for this element if we can't get them
                    pass

    # Augment with DOM-based discovery: surfaces ARIA-less controls (custom
    # `datarole`, `div` grid rows/cells, `kd-*` widgets) the AX tree can't see.
    # When a control is found both ways (same backend node id), ENRICH the AX
    # entry with the DOM-only signal — the custom `datarole`, and a text label
    # when the AX name was empty — rather than dropping it (that would lose the
    # only handle the agent has on an unlabelled input). DOM-only hits are
    # appended; they already carry x/y/box from the scan.
    if dom_scan:
        ax_by_backend = {
            nid: e
            for e in elements
            if (nid := node_id_of(e.get("ref", ""))) is not None
        }
        for de in await _dom_scan(tab, text=text, limit=dom_limit):
            existing = ax_by_backend.get(node_id_of(de["ref"]))
            if existing is None:
                elements.append(de)
                continue
            if de.get("datarole") and not existing.get("datarole"):
                existing["datarole"] = de["datarole"]
            if not existing.get("name") and de.get("name"):
                existing["name"] = de["name"]

    return elements
