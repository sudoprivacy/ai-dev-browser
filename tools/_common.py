"""Common utilities for nodriver-kit CLI tools.

All tools share this module for consistent behavior:
- JSON output for AI parsing
- Unified --port argument
- Error handling
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import nodriver


def output(data: dict) -> None:
    """Output JSON to stdout for AI parsing."""
    print(json.dumps(data, ensure_ascii=False, indent=2))


def error(message: str, code: int = 1) -> None:
    """Output error and exit."""
    output({"error": message})
    sys.exit(code)


def add_port_arg(parser: argparse.ArgumentParser) -> None:
    """Add common --port argument."""
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=9222,
        help="Chrome debugging port (default: 9222)"
    )


async def connect_browser(port: int) -> nodriver.Browser:
    """Connect to existing Chrome instance."""
    try:
        browser = await nodriver.start(
            host="127.0.0.1",
            port=port,
        )
        return browser
    except Exception as e:
        error(f"Failed to connect to Chrome on port {port}: {e}")


async def get_active_tab(browser: nodriver.Browser):
    """Get the active/main tab from browser."""
    # Try to find existing tab
    targets = getattr(browser, "targets", None) or []
    page_targets = [t for t in targets if getattr(t, "type_", "") == "page"]

    for target in page_targets:
        url = getattr(target, "url", "") or ""
        if url and not url.startswith("about:"):
            return target

    if page_targets:
        return page_targets[0]

    # No tabs, create one
    return await browser.get("about:blank")


def run_async(coro):
    """Run async function."""
    return asyncio.run(coro)
