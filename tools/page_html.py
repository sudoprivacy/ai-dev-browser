#!/usr/bin/env python3
"""Get page HTML content.

Usage:
    python tools/page_html.py [--port 9222] [--output /tmp/page.html]
    python tools/page_html.py [--port 9222] --selector "div.content"

Output:
    {"html": "...", "length": 1234} or {"path": "/tmp/page.html"}
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools._common import output, error, add_port_arg, connect_browser, get_active_tab, run_async


async def main_async(args):
    browser = await connect_browser(args.port)
    tab = await get_active_tab(browser)

    try:
        if args.selector:
            js_code = f"document.querySelector({repr(args.selector)})?.outerHTML || ''"
        else:
            js_code = "document.documentElement.outerHTML"

        html = await tab.evaluate(js_code)

        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(html, encoding="utf-8")
            output({
                "path": str(output_path),
                "length": len(html),
                "message": f"HTML saved to {output_path}"
            })
        else:
            # Truncate for JSON output
            if len(html) > 10000:
                html_preview = html[:10000] + f"\n... (truncated, total {len(html)} chars)"
            else:
                html_preview = html

            output({
                "html": html_preview,
                "length": len(html)
            })

    except Exception as e:
        error(f"Failed to get HTML: {e}")


def main():
    parser = argparse.ArgumentParser(description="Get page HTML")
    add_port_arg(parser)
    parser.add_argument("--output", "-o", help="Save HTML to file")
    parser.add_argument("--selector", "-s", help="Get HTML of specific element")
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
