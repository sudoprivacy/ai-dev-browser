# nodriver-kit

A browser for AI agents. Built on [nodriver](https://github.com/ultrafunkamsterdam/nodriver) - human-like automation that works seamlessly in a world designed for humans.

## Why nodriver?

**nodriver mimics human behavior** - making it ideal for:

- **AI Agents**: Best choice for AI-driven browser automation. nodriver's human-like interactions avoid detection and work with sites that block traditional automation tools.
- **UI Testing**: Tests that behave like real users, catching issues that robotic automation misses.
- **Web Scraping**: Access sites that detect and block Selenium/Puppeteer/Playwright.

Unlike Selenium (sends "I'm a robot" signals) or Playwright (fast but detectable), nodriver:
- Uses actual Chrome via CDP (Chrome DevTools Protocol)
- Implements human-like delays and movements
- Passes Cloudflare, bot detection, and CAPTCHAs
- Works where other tools fail

## Features

- **Human-like Automation**: Built on nodriver's anti-detection technology
- **Browser Management**: Cross-platform Chrome detection, launching, and port management
- **Worker Pool**: Parallel task execution with multiple browser instances
- **Dual-Interface Tools**: Every tool works as both CLI command and Python import
- **AI-Friendly API**: Intuitive `run()` method, sensible defaults, clear error messages

## Installation

```bash
pip install nodriver-kit
```

For Cloudflare bypass support (uses nodriver's built-in `verify_cf()`):
```bash
pip install nodriver-kit[cv]
```

## Quick Start

### Simple Browser Launch

```python
from nodriver_kit import find_chrome, launch_chrome, get_available_port
import nodriver as uc

# Find available port and launch Chrome
port = get_available_port()
process = launch_chrome(port=port)

# Connect with nodriver
browser = await uc.start(browser_args=[f"--remote-debugging-port={port}"])
tab = await browser.get("https://example.com")
```

### Worker Pool for Parallel Tasks

```python
from nodriver_kit import BrowserPool

class MyClient:
    def __init__(self, port: int, headless: bool = False):
        self.port = port
        self.headless = headless

    async def __aenter__(self):
        import nodriver as uc
        self.browser = await uc.start(
            browser_args=[f"--remote-debugging-port={self.port}"],
            headless=self.headless,
        )
        return self

    async def __aexit__(self, *args):
        self.browser.stop()

    async def fetch(self, url: str) -> dict:
        tab = await self.browser.get(url)
        return {"url": url, "title": await tab.title}

# Run 3 workers in parallel
async with BrowserPool(MyClient, workers=3) as pool:
    # Submit tasks using AI-friendly "run" method
    await pool.run("fetch", "https://example.com")
    await pool.run("fetch", "https://google.com")
    await pool.run("fetch", "https://github.com")

    # Wait for all to complete
    results = await pool.wait()
    for job_id, result in results.items():
        print(f"{result.data['url']}: {result.data['title']}")
```

### Cloudflare Bypass

Use nodriver's built-in `verify_cf()`:

```python
import nodriver as uc

browser = await uc.start()
tab = await browser.get("https://protected-site.com")
await tab.verify_cf()  # Built-in CF bypass (requires opencv-python)
```

## Tools: CLI & Python, Same Code

**Design Philosophy**: Write once, use two ways.

Every tool in `nodriver_kit/tools/` works as both a CLI command and a Python function. No translation layer, no duplication - the same code serves both interfaces.

```bash
# Discover all tools
ls nodriver_kit/tools/
```

### As CLI (for exploration & scripting)

```bash
# Start browser (uses default profile for persistence)
python -m nodriver_kit.tools.browser_start --url "https://example.com"

# Get accessibility tree
python -m nodriver_kit.tools.ax_tree --port 9222

# Click element by ref
python -m nodriver_kit.tools.ax_select --port 9222 --ref 5

# Take screenshot
python -m nodriver_kit.tools.page_screenshot --port 9222 --path ./shot.png

# Stop browser
python -m nodriver_kit.tools.browser_stop --port 9222
```

### As Python (for codification)

```python
from nodriver_kit.core import connect_browser, get_active_tab
from nodriver_kit.tools import browser_start, ax_tree, ax_select, page_screenshot

# Start browser with default profile
result = browser_start(url="https://example.com")
browser = await connect_browser(port=result["port"])
tab = await get_active_tab(browser)

# Find and click using accessibility tree
tree = await ax_tree(tab, interactable_only=True)
await ax_select(tab, node_id=tree[0]["_nodeId"])
await page_screenshot(tab, path="./shot.png")
```

### Available Tools

```bash
ls nodriver_kit/tools/                        # Discover all tools
python -m nodriver_kit.tools.<name> --help    # Usage for any tool
```

## API Reference

### Browser Module

```python
from nodriver_kit import (
    find_chrome,           # Find Chrome executable
    launch_chrome,         # Launch Chrome with debug port
    get_available_port,    # Get next available port
    is_port_in_use,        # Check if port is occupied
    find_temp_chromes,     # Find Chrome instances launched by this lib
    kill_process_tree,     # Terminate process and children
)
```

### Pool Module

```python
from nodriver_kit import (
    BrowserPool,           # Main pool class
    Job,                   # Task representation
    JobResult,             # Task result
    JobStatus,             # Task status enum
    Worker,                # Worker representation
    WorkerStats,           # Worker statistics
)
```

## Requirements

- Python 3.10+
- nodriver >= 0.38
- websocket-client >= 1.0

## License

MIT
