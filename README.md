# ai-dev-browser

A browser for AI to develop web automation — human-like automation that works seamlessly in a world designed for humans.

## What is this?

**ai-dev-browser gives AI agents (Claude, GPT, etc.) tools to see and interact with web pages** — similar to how [Claude in Chrome](https://claude.com/chrome) works, but headless-compatible and embeddable.

Two interaction modes:
- **Accessibility tree** (`page_find`): semantic element discovery with refs for clicking/typing
- **Screenshots** (`page_screenshot` + `mouse_click --screenshot`): visual coordinate-based interaction with automatic scaling

```bash
# AI discovers elements
python -m ai_dev_browser.tools.page_find

# AI clicks by ref (from accessibility tree)
python -m ai_dev_browser.tools.click_by_ref --ref "5#214"

# AI clicks by coordinates (from screenshot)
python -m ai_dev_browser.tools.mouse_click --x 105 --y 52 --screenshot screenshots/page.png
```

## Screenshot Coordinate Alignment

Screenshots are automatically scaled to fit LLM vision limits (default: 1280px long edge for Claude). Scaling metadata is embedded in the PNG file. When you pass `--screenshot` to mouse tools, coordinates are auto-converted from screenshot space to CSS viewport space.

```bash
# Take screenshot (auto-scaled, metadata embedded in PNG)
python -m ai_dev_browser.tools.page_screenshot
# → screenshots/20260325_210000.png (1280x800)

# Click using coordinates from the screenshot — auto-scaled
python -m ai_dev_browser.tools.mouse_click --x 78 --y 117 --screenshot screenshots/20260325_210000.png
```

Configurable per model:
```python
await screenshot(tab, max_long_edge=1280)   # Claude (default)
await screenshot(tab, max_long_edge=2048)   # GPT-4o
await screenshot(tab, max_long_edge=0)      # Gemini (unlimited)
```

## CLI = Python (SSOT)

Every tool works as both CLI command and Python function. Parameters are defined once in core functions, CLI tools are auto-generated. See [cli-args-ssot](https://github.com/sudoprivacy/cli-args-ssot).

```bash
python -m ai_dev_browser.tools.click_by_text --text "Sign in"
```

```python
from ai_dev_browser.core import click_by_text
await click_by_text(tab, text="Sign in")
```

41 tools covering: navigation, element interaction, mouse, tabs, screenshots, cookies, storage, window management, dialogs, downloads, raw CDP, and Cloudflare bypass.

```bash
ls ai_dev_browser/tools/  # See all available tools
```

## Quick Start

```bash
pip install ai-dev-browser
```

```python
from ai_dev_browser.core import goto, click_by_text, type_by_text, screenshot

await goto(tab, "https://example.com")
await type_by_text(tab, name="Email", text="user@example.com")
await click_by_text(tab, text="Sign in")
await screenshot(tab)  # → screenshots/{timestamp}.png
```

## Human-like Behavior

CDP-dispatched events produce `isTrusted=true`. Optional human-like features (all off by default, opt-in):

```python
from ai_dev_browser.core import human

human.configure(
    use_gaussian_path=True,    # Bezier mouse curves (+50ms)
    click_hold_enabled=True,   # Hold before release (+45ms)
    type_humanize=True,        # Typing delays (+35ms/char)
)
```

Default: click offset randomization (free, always on). Everything else is opt-in for speed.

## Architecture

- **CDP WebSocket transport** (`_transport.py`): direct Chrome DevTools Protocol, no browser automation framework dependency
- **Auto-reconnect**: tab WebSocket reconnection with target re-discovery (handles Electron SPA navigation)
- **Connection reuse**: same `host:port` shares one `BrowserClient` instance across calls
- **CDP module**: vendored from [nodriver](https://github.com/ultrafunkamsterdam/nodriver) via git submodule (`scripts/sync_cdp.py` to update)

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `AI_DEV_BROWSER_PORT` | Default CDP port (skips auto-detection) |
| `AI_DEV_BROWSER_HEADLESS` | Default headless mode (`1`/`true`) |
| `AI_DEV_BROWSER_REDIRECT` | Block direct CLI, print redirect message |

## License

AGPL-3.0
