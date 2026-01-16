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
- **CLI Tools**: 37 standalone tools for AI agents and scripting (see [tools/](tools/README.md))
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

## CLI Tools

37 standalone tools for AI agents and scripting. Key tools:

```bash
# AI-friendly page snapshot (accessibility tree - best for AI)
python tools/page_snapshot.py --port 9222

# Browser management
python tools/browser_start.py
python tools/browser_stop.py --all

# Navigation
python tools/page_goto.py --url "https://example.com"
python tools/element_click.py --selector "button.submit"

# Tab management
python tools/tab_new.py --url "https://google.com"
python tools/tab_list.py
```

See [tools/README.md](tools/README.md) for all 37 tools.

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
