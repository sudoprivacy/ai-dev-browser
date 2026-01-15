#!/usr/bin/env python3
"""Get AI-friendly accessibility tree snapshot of the page.

This is the most important tool for AI agents - it returns a semantic
representation of the page that's much more useful than raw HTML.

Usage:
    python tools/page_snapshot.py [--port 9222]
    python tools/page_snapshot.py --max-depth 5
    python tools/page_snapshot.py --format yaml
    python tools/page_snapshot.py --interactable  # Only show clickable/typable elements

Output:
    Accessibility tree in JSON or YAML format, showing:
    - role: button, link, textbox, heading, etc.
    - name: visible text or aria-label
    - value: current value for inputs
    - focused/disabled/required states
    - ref: unique reference ID for use with element_click/element_type

Example output:
    [
      {"ref": "1", "role": "link", "name": "Home"},
      {"ref": "2", "role": "button", "name": "Sign in"},
      {"ref": "3", "role": "textbox", "name": "Email", "focused": true},
      {"ref": "4", "role": "heading", "name": "Welcome", "level": 1}
    ]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools._common import (
    output,
    error,
    add_port_arg,
    connect_browser,
    get_active_tab,
    run_async,
)


def format_ax_node(
    node, ref_counter, max_depth, current_depth=0, interactable_only=False
):
    """Format an accessibility node into AI-friendly structure."""
    results = []

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

    # Skip ignored nodes and nodes without useful info
    if role in ("none", "generic", "InlineTextBox", "LineBreak"):
        # But still process children
        if hasattr(node, "children") and node.children:
            for child in node.children:
                results.extend(
                    format_ax_node(
                        child,
                        ref_counter,
                        max_depth,
                        current_depth + 1,
                        interactable_only,
                    )
                )
        return results

    # Determine if this node is interactable
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

    # Skip non-interactable nodes if filter is on
    if (
        interactable_only
        and not is_interactable
        and role not in ("heading", "img", "alert")
    ):
        if hasattr(node, "children") and node.children:
            for child in node.children:
                results.extend(
                    format_ax_node(
                        child,
                        ref_counter,
                        max_depth,
                        current_depth + 1,
                        interactable_only,
                    )
                )
        return results

    # Build the node info
    if role and (name or is_interactable):
        ref_counter[0] += 1
        info = {
            "ref": str(ref_counter[0]),
            "role": role,
        }

        if name:
            info["name"] = name[:100]  # Truncate long names

        # Add value for inputs
        if hasattr(node, "value") and node.value:
            val = node.value.value if hasattr(node.value, "value") else str(node.value)
            if val:
                info["value"] = val[:50]

        # Add important states
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

        # Add level for headings
        if role == "heading" and props.get("level"):
            info["level"] = props["level"]

        # Store backend node ID for clicking (internal use)
        if hasattr(node, "backend_dom_node_id") and node.backend_dom_node_id:
            info["_nodeId"] = node.backend_dom_node_id

        results.append(info)

    # Process children
    if hasattr(node, "children") and node.children:
        for child in node.children:
            results.extend(
                format_ax_node(
                    child, ref_counter, max_depth, current_depth + 1, interactable_only
                )
            )

    return results


async def main_async(args):
    import nodriver.cdp.accessibility as accessibility

    browser = await connect_browser(args.port)
    tab = await get_active_tab(browser)

    try:
        # Enable accessibility domain
        await tab.send(accessibility.enable())

        # Get the full accessibility tree
        result = await tab.send(accessibility.get_full_ax_tree())

        # Handle both list and object with .nodes attribute
        ax_nodes = result.nodes if hasattr(result, "nodes") else result
        if not ax_nodes:
            output(
                {
                    "snapshot": [],
                    "count": 0,
                    "message": "No accessibility tree available",
                }
            )
            return

        # Find root node and format tree
        ref_counter = [0]
        nodes = []

        # The first node is usually the root
        for node in ax_nodes:
            if hasattr(node, "role") and node.role:
                formatted = format_ax_node(
                    node,
                    ref_counter,
                    args.max_depth,
                    interactable_only=args.interactable,
                )
                nodes.extend(formatted)

        # Remove duplicates while preserving order
        seen_refs = set()
        unique_nodes = []
        for n in nodes:
            ref = n.get("ref")
            if ref not in seen_refs:
                seen_refs.add(ref)
                unique_nodes.append(n)

        if args.format == "yaml":
            # Simple YAML-like format
            lines = []
            for n in unique_nodes:
                parts = [f"[{n['ref']}]", n["role"]]
                if n.get("name"):
                    parts.append(f'"{n["name"]}"')
                if n.get("value"):
                    parts.append(f'value="{n["value"]}"')
                for state in ["focused", "disabled", "checked", "selected", "expanded"]:
                    if n.get(state) is not None:
                        parts.append(f"{state}={n[state]}")
                lines.append(" ".join(parts))
            output(
                {
                    "snapshot": "\n".join(lines),
                    "count": len(unique_nodes),
                    "format": "yaml",
                }
            )
        else:
            output(
                {"snapshot": unique_nodes, "count": len(unique_nodes), "format": "json"}
            )

    except Exception as e:
        error(f"Failed to get accessibility tree: {e}")


def main():
    parser = argparse.ArgumentParser(description="Get page accessibility snapshot")
    add_port_arg(parser)
    parser.add_argument(
        "--max-depth", type=int, default=10, help="Max tree depth (default: 10)"
    )
    parser.add_argument(
        "--format", choices=["json", "yaml"], default="json", help="Output format"
    )
    parser.add_argument(
        "--interactable",
        "-i",
        action="store_true",
        help="Only show interactable elements (buttons, links, inputs, etc.)",
    )
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
