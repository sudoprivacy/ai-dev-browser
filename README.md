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
- **Dual-Interface Tools**: 37 tools that work as both CLI commands and Python imports
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
# Start browser
python -m nodriver_kit.tools.browser_start --port 9222

# Navigate
python -m nodriver_kit.tools.goto --port 9222 --url "https://example.com"

# Find element
python -m nodriver_kit.tools.find --port 9222 --selector "a"
# {"found": true, "tag": "a", "text": "Learn more"}

# Click it
python -m nodriver_kit.tools.click --port 9222 --text "Learn more"

# Take screenshot
python -m nodriver_kit.tools.screenshot --port 9222 --path ./shot.png

# Stop browser
python -m nodriver_kit.tools.browser_stop --port 9222
```

### As Python (for codification)

```python
from nodriver_kit.tools import (
    browser_start, goto, find, click, screenshot, browser_stop
)

# Same tools, programmatic interface
result = browser_start(port=9222)
await goto(tab, url="https://example.com")
elem = await find(tab, selector="a")
await click(tab, text="Learn more")
await screenshot(tab, path="./shot.png")
browser_stop(port=9222)
```

### Available Tools (37 total)

| Category | Tools |
|----------|-------|
| **Browser** | `browser_start`, `browser_stop`, `browser_list` |
| **Page** | `goto`, `reload`, `page_info`, `page_wait`, `screenshot`, `snapshot`, `html` |
| **Elements** | `find`, `click`, `type_text`, `element_wait`, `xpath`, `evaluate` |
| **Wait** | `wait_url` |
| **Mouse** | `mouse_click`, `mouse_move`, `mouse_drag` |
| **Tabs** | `tab_new`, `tab_list`, `tab_switch`, `tab_close` |
| **Scroll** | `scroll` |
| **Cookies** | `cookies_list`, `cookies_save`, `cookies_load` |
| **Storage** | `storage_get`, `storage_set` |
| **Window** | `window_resize`, `window_state` |
| **Download** | `download_file`, `download_path` |
| **Session** | `login_interactive` |
| **Advanced** | `cdp_send`, `cf_verify` |

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
