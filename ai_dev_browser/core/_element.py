"""Element class and DOM tree utilities."""

from __future__ import annotations

import logging
import typing

from ai_dev_browser.cdp import dom, input_ as cdp_input, runtime

if typing.TYPE_CHECKING:
    from ._tab import Tab

logger = logging.getLogger(__name__)


# =============================================================================
# DOM tree utilities
# =============================================================================


def filter_recurse(doc, predicate):
    """Find first node in DOM tree matching predicate (depth-first, incl. shadow DOM)."""
    if not hasattr(doc, "children") or not doc.children:
        return None
    for child in doc.children:
        if predicate(child):
            return child
        if child.shadow_roots:
            result = filter_recurse(child.shadow_roots[0], predicate)
            if result:
                return result
        result = filter_recurse(child, predicate)
        if result:
            return result
    return None


def filter_recurse_all(doc, predicate):
    """Find all nodes in DOM tree matching predicate (depth-first, incl. shadow DOM)."""
    if not hasattr(doc, "children") or not doc.children:
        return []
    out = []
    for child in doc.children:
        if predicate(child):
            out.append(child)
        if child.shadow_roots:
            out.extend(filter_recurse_all(child.shadow_roots[0], predicate))
        out.extend(filter_recurse_all(child, predicate))
    return out


# =============================================================================
# Position
# =============================================================================


class Position:
    """Element position from content quads."""

    def __init__(self, points):
        (
            self.left,
            self.top,
            _right_top_x,
            _right_top_y,
            self.right,
            self.bottom,
            _left_bottom_x,
            _left_bottom_y,
        ) = points
        self.x = self.left
        self.y = self.top
        self.width = self.right - self.left
        self.height = self.bottom - self.top
        self.center = (
            self.left + self.width / 2,
            self.top + self.height / 2,
        )
        self.abs_x: float = 0
        self.abs_y: float = 0

    def __repr__(self):
        return f"<Position(x={self.left}, y={self.top}, width={self.width}, height={self.height})>"


# =============================================================================
# Element
# =============================================================================


def create(node: dom.Node, tab: Tab, tree: dom.Node | None = None) -> Element:
    """Factory for Element objects."""
    return Element(node, tab, tree)


class Element:
    """Wraps a CDP DOM node with convenience methods.

    Only implements methods used by ai-dev-browser core/:
    click, send_keys, clear_input, get_position, scroll_into_view,
    apply, focus, text, text_all.
    """

    def __init__(self, node: dom.Node, tab: Tab, tree: dom.Node | None = None):
        if not node:
            raise ValueError("node cannot be None")
        self._tab = tab
        self._node = node
        self._tree = tree
        self._remote_object: runtime.RemoteObject | None = None

    @property
    def node(self) -> dom.Node:
        return self._node

    @property
    def tab(self) -> Tab:
        return self._tab

    @property
    def backend_node_id(self) -> dom.BackendNodeId:
        return self._node.backend_node_id

    @property
    def node_name(self) -> str:
        return self._node.node_name or ""

    @property
    def node_type(self) -> int:
        return self._node.node_type

    @property
    def remote_object(self) -> runtime.RemoteObject | None:
        return self._remote_object

    @property
    def object_id(self) -> runtime.RemoteObjectId | None:
        if self._remote_object:
            return self._remote_object.object_id
        return None

    @property
    def text(self) -> str:
        """Get text content of this element (first text node)."""
        text_node = filter_recurse(self._node, lambda n: n.node_type == 3)
        if text_node:
            return text_node.node_value or ""
        return ""

    @property
    def text_all(self) -> str:
        """Get concatenated text of this element and all children."""
        text_nodes = filter_recurse_all(self._node, lambda n: n.node_type == 3)
        return " ".join(n.node_value for n in text_nodes if n.node_value)

    async def _resolve(self) -> runtime.RemoteObject:
        """Resolve node to RemoteObject for JS operations."""
        self._remote_object = await self._tab.send(
            dom.resolve_node(backend_node_id=self.backend_node_id)
        )
        return self._remote_object

    async def apply(self, js_function: str, return_by_value: bool = True):
        """Execute JS function on this element.

        Args:
            js_function: JS function that receives this element as parameter.
                         e.g. '(el) => el.value' or 'function(el) { el.click() }'
            return_by_value: If True, return the JS value. If False, return RemoteObject.
        """
        await self._resolve()
        result = await self._tab.send(
            runtime.call_function_on(
                js_function,
                object_id=self._remote_object.object_id,
                arguments=[
                    runtime.CallArgument(object_id=self._remote_object.object_id)
                ],
                return_by_value=True,
                user_gesture=True,
            )
        )
        if result and result[0]:
            return result[0].value if return_by_value else result[0]
        if result and result[1]:
            return result[1]
        return None

    async def click(self):
        """Click element via JS el.click()."""
        await self._resolve()
        await self._tab.send(
            runtime.call_function_on(
                "(el) => el.click()",
                object_id=self._remote_object.object_id,
                arguments=[
                    runtime.CallArgument(object_id=self._remote_object.object_id)
                ],
                await_promise=True,
                user_gesture=True,
                return_by_value=True,
            )
        )

    async def mouse_click(self, button: str = "left", modifiers: int = 0):
        """Click element via CDP mouse events (isTrusted=true).

        More reliable than click() for UI frameworks (React, etc.) that
        depend on real mouse events.

        Args:
            button: "left", "right", or "middle"
            modifiers: Modifier keys bitmask (1=Alt, 2=Ctrl, 4=Meta, 8=Shift)
        """
        pos = await self.get_position()
        x, y = pos.center
        await self._tab.mouse_click(x, y, button=button, modifiers=modifiers)

    async def send_keys(self, text: str):
        """Send keystrokes to this element."""
        await self.apply("(elem) => elem.focus()")
        for char in text:
            await self._tab.send(cdp_input.dispatch_key_event("char", text=char))

    async def clear_input(self):
        """Clear an input field."""
        await self.apply('function (element) { element.value = "" }')

    async def get_position(self) -> Position:
        """Get element position and dimensions."""
        if not self.object_id:
            await self._resolve()
        quads = await self._tab.send(
            dom.get_content_quads(object_id=self._remote_object.object_id)
        )
        if not quads:
            raise Exception(f"Could not find position for {self}")
        return Position(quads[0])

    async def scroll_into_view(self):
        """Scroll element into view if needed."""
        try:
            await self._tab.send(
                dom.scroll_into_view_if_needed(backend_node_id=self.backend_node_id)
            )
        except Exception as e:
            logger.debug("Could not scroll into view: %s", e)

    async def focus(self):
        """Focus this element."""
        await self.apply("(element) => element.focus()")

    async def update(self, _node=None):
        """Re-fetch DOM and update node reference + remote_object."""
        if _node:
            doc = _node
        else:
            doc = await self._tab.send(dom.get_document(-1, True))
        updated = filter_recurse(
            doc, lambda n: n.backend_node_id == self._node.backend_node_id
        )
        if updated:
            self._node = updated
        self._tree = doc
        self._remote_object = await self._tab.send(
            dom.resolve_node(backend_node_id=self._node.backend_node_id)
        )
        return self

    async def mouse_move(self):
        """Move mouse to element center (hover)."""
        pos = await self.get_position()
        x, y = pos.center
        await self._tab.mouse_move(x, y)

    async def get_html(self) -> str:
        """Get element's outerHTML."""
        await self._resolve()
        return await self._tab.send(
            dom.get_outer_html(backend_node_id=self.backend_node_id)
        )

    async def select_option(self):
        """Select this option element (for <select> dropdowns)."""
        await self.apply(
            "(el) => { el.selected = true; "
            "el.dispatchEvent(new Event('change', {bubbles: true})); }"
        )

    async def send_file(self, *paths: str):
        """Set file paths on a file input element."""
        await self._tab.send(
            dom.set_file_input_files(list(paths), backend_node_id=self.backend_node_id)
        )

    async def query_selector(self, selector: str):
        """Find a child element by CSS selector."""
        doc = self._tree or await self._tab.send(dom.get_document(-1, True))
        node_id = await self._tab.send(dom.query_selector(self._node.node_id, selector))
        if not node_id:
            return None
        node = filter_recurse(doc, lambda n: n.node_id == node_id)
        return create(node, self._tab, doc) if node else None

    async def query_selector_all(self, selector: str):
        """Find all child elements by CSS selector."""
        doc = self._tree or await self._tab.send(dom.get_document(-1, True))
        node_ids = await self._tab.send(
            dom.query_selector_all(self._node.node_id, selector)
        )
        if not node_ids:
            return []
        return [
            create(node, self._tab, doc)
            for nid in node_ids
            if (node := filter_recurse(doc, lambda n: n.node_id == nid))
        ]

    def __repr__(self):
        name = self.node_name
        text = self.text[:30] if self.text else ""
        return f"<Element({name}, text={text!r})>"
