#!/usr/bin/env python3
"""Find elements on the page.

Usage:
    python tools/element_find.py --text "Login" [--port 9222]
    python tools/element_find.py --selector "button.submit" [--port 9222]

Output:
    {"found": true, "count": 1, "elements": [{"tag": "button", "text": "Login", "selector": "..."}]}
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools._common import output, error, add_port_arg, connect_browser, get_active_tab, run_async


async def main_async(args):
    browser = await connect_browser(args.port)
    tab = await get_active_tab(browser)

    elements_data = []

    if args.text:
        # Find by text content
        try:
            elements = await tab.find_all(args.text)
            for elem in elements[:10]:  # Limit to 10
                tag = getattr(elem, "tag_name", None) or await elem.evaluate("this.tagName")
                text = getattr(elem, "text", None) or await elem.evaluate("this.textContent")
                elements_data.append({
                    "tag": tag.lower() if tag else "unknown",
                    "text": (text or "")[:100].strip(),
                })
        except Exception as e:
            pass

    elif args.selector:
        # Find by CSS selector
        try:
            js_code = f"""
            (() => {{
                const elements = document.querySelectorAll({repr(args.selector)});
                return Array.from(elements).slice(0, 10).map(el => ({{
                    tag: el.tagName.toLowerCase(),
                    text: (el.textContent || '').slice(0, 100).trim(),
                    id: el.id || null,
                    className: el.className || null
                }}));
            }})()
            """
            result = await tab.evaluate(js_code)
            if result:
                elements_data = result
        except Exception as e:
            error(f"Selector query failed: {e}")

    output({
        "found": len(elements_data) > 0,
        "count": len(elements_data),
        "elements": elements_data
    })


def main():
    parser = argparse.ArgumentParser(description="Find elements")
    add_port_arg(parser)
    parser.add_argument("--text", "-t", help="Find by text content")
    parser.add_argument("--selector", "-s", help="Find by CSS selector")
    args = parser.parse_args()

    if not args.text and not args.selector:
        error("Must specify --text or --selector")

    run_async(main_async(args))


if __name__ == "__main__":
    main()
