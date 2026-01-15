"""Common utilities for nodriver-kit CLI tools.

All tools share this module for consistent behavior:
- JSON output for AI parsing
- Unified --port argument
- Error handling

Uses nodriver_kit.core for browser operations.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Use core module for browser operations
sys.path.insert(0, str(Path(__file__).parent.parent))
from nodriver_kit.core import connect_browser as _connect_browser
from nodriver_kit.core import get_active_tab as _get_active_tab


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
        "--port",
        "-p",
        type=int,
        default=9222,
        help="Chrome debugging port (default: 9222)",
    )


async def connect_browser(port: int):
    """Connect to existing Chrome instance."""
    try:
        return await _connect_browser(port=port)
    except Exception as e:
        error(f"Failed to connect to Chrome on port {port}: {e}")


async def get_active_tab(browser):
    """Get the active/main tab from browser."""
    return await _get_active_tab(browser)


def run_async(coro):
    """Run async function."""
    return asyncio.run(coro)
