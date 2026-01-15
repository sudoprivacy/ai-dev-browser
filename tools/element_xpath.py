#!/usr/bin/env python3
"""Find elements using XPath.

Usage:
    python tools/element_xpath.py --xpath "//button[@type='submit']"
    python tools/element_xpath.py --xpath "//div[@class='content']//a"

Output:
    {"found": true, "count": 2, "elements": [{"tag": "a", "text": "Link 1"}, ...]}
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


async def main_async(args):
    browser = await connect_browser(args.port)
    tab = await get_active_tab(browser)

    try:
        elements = await tab.xpath(args.xpath)

        if not elements:
            output(
                {
                    "found": False,
                    "count": 0,
                    "elements": [],
                    "message": f"No elements found for xpath: {args.xpath}",
                }
            )
            return

        elements_info = []
        for elem in elements[: args.limit]:
            info = {
                "tag": elem.tag_name if hasattr(elem, "tag_name") else "unknown",
            }

            # Get text content
            if hasattr(elem, "text"):
                text = elem.text or ""
                if text:
                    info["text"] = text[:100]

            # Get common attributes
            for attr in ["id", "class", "href", "src", "name", "type", "value"]:
                try:
                    val = getattr(elem, attr, None) or elem.attrs.get(attr)
                    if val:
                        info[attr] = str(val)[:100]
                except Exception:
                    pass

            elements_info.append(info)

        output(
            {
                "found": True,
                "count": len(elements),
                "elements": elements_info,
                "message": f"Found {len(elements)} element(s)",
            }
        )

    except Exception as e:
        error(f"XPath query failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Find elements by XPath")
    add_port_arg(parser)
    parser.add_argument("--xpath", "-x", required=True, help="XPath expression")
    parser.add_argument(
        "--limit",
        "-l",
        type=int,
        default=10,
        help="Max elements to return (default: 10)",
    )
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
