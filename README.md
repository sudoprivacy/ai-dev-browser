# ai-dev-browser

A browser for AI to develop web automation — human-like automation that works seamlessly in a world designed for humans. Built on [nodriver](https://github.com/ultrafunkamsterdam/nodriver).

## What is this?

**ai-dev-browser is designed for AI agents (like Claude) to explore websites and build automation scripts.**

The workflow:
1. **Explore** (CLI): AI uses tools like `ax_tree`, `page_screenshot` to understand a webpage
2. **Develop** (Python): AI codifies the automation using the same functions
3. **Run**: The automation runs reliably with human-like behavior

This is not a traditional testing framework — it's a development environment where AI is the developer.

## Human-like Automation (Priority 1)

**ai-dev-browser mimics human behavior** — this is our core feature:

- **Mouse**: Gaussian random walk + Bezier curves (not linear paths that bots use)
- **Clicks**: Random offset within element bounds (±20%), not always dead center
- **Events**: CDP dispatch produces `isTrusted=true` (JS `.click()` produces `isTrusted=false`)
- **Timing**: Configurable delays, from pro-gamer speed (30-60ms) to natural pace

Unlike Selenium (detectable via `navigator.webdriver`), Playwright (fast but predictable), or Puppeteer (still detectable movements), ai-dev-browser works where others get blocked.

## CLI = Python (SSOT)

**Why SSOT matters for AI:**

1. **Seamless exploration**: AI can `ls tools/` to discover capabilities, then directly use the same functions to build automation
2. **Autoregressive learning**: When AI improves a function, it only edits one place — changes propagate to both CLI and Python automatically
3. **Meta-learning friendly**: AI can inspect, modify, and extend tools without maintaining duplicate definitions

```bash
python -m ai_dev_browser.tools.element_click --selector "#btn" --human-like
```

```python
from ai_dev_browser.core import click
await click(tab, selector="#btn", human_like=True)
```

We maintain SSOT rigorously. See [cli-args-ssot](https://github.com/sudoprivacy/cli-args-ssot) for our verification checklist.

**Related**: The [browser-automation-creator](https://github.com/sudoprivacy/browser-automation-creator) skill uses this library to help AI build custom browser automation tools.

## Quick Start

```python
from ai_dev_browser.core import click, type_text, goto

await goto(tab, "https://example.com")
await click(tab, selector="#login")
await type_text(tab, "user@example.com", selector="#email")
```

## Human Behavior Config

```python
from ai_dev_browser.core import human

human.configure(
    use_gaussian_path=True,    # Curved mouse movements (+50ms)
    click_hold_enabled=True,   # Hold before release (+45ms)
    type_humanize=True,        # Typing delays (+35ms/char)
)
```

**Default philosophy**: FREE features ON (click offset), costly features OFF (opt-in).

**Advanced**: For custom automation, `generate_gaussian_path()` and `calculate_click_offset()` are available from `ai_dev_browser.core.human`.

## Installation

```bash
pip install ai-dev-browser
```

## Tools

```bash
python -m ai_dev_browser.tools.<name> --help
```

Navigation, clicks, typing, mouse, tabs, scroll, storage, screenshots — all available as CLI and Python.

## License

AGPL-3.0 (to maintain compatibility with [nodriver](https://github.com/ultrafunkamsterdam/nodriver) which is AGPL-licensed)
