# ai-dev-browser

A browser for AI to develop web automation — human-like automation that works seamlessly in a world designed for humans.

## What is this?

**ai-dev-browser is a browser that AI agents (Claude, GPT, etc.) use to see and interact with web pages** — similar to how [Claude in Chrome](https://claude.com/chrome) works, but headless-compatible and embeddable.

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

49 tools covering: navigation, element interaction, mouse, tabs, screenshots, cookies, storage, window management, dialogs, downloads, raw CDP, and Cloudflare bypass.

```bash
ls ai_dev_browser/tools/  # See all available tools
```

### Tool Naming Convention

Most element-targeting tools follow `<verb>_by_<spec>` — verb is the action,
spec is how you identify the element. LLM mental model: "I have an X, I want
to do Y → look for `Y_by_X`."

| Spec        | Source                                        | Example tool        |
|-------------|-----------------------------------------------|---------------------|
| `_by_ref`   | ref returned by `page_discover` (AX tree)     | `click_by_ref`      |
| `_by_text`  | visible text content                          | `click_by_text`     |
| `_by_html_id` | `id="..."` HTML attribute (cross-frame)     | `click_by_html_id`  |
| `_by_xpath` | XPath expression (`document.evaluate`)        | `click_by_xpath`    |

Verbs currently in use: `click`, `type`, `focus`, `hover`, `drag`, `highlight`,
`html` (read), `screenshot`, `select`, `upload`, `find`.

`page_*` tools operate on the whole page (`page_goto`, `page_screenshot`,
`page_discover`, `page_scroll`). `page_discover` is broad exploration;
`find_by_*` is targeted single-element lookup.

### Docstring First-Line Convention

Every tool's docstring **first sentence is a decision signal, not a
description**. Two halves, always in this order:

1. **Input (when to pick me)** — the condition that makes *this* tool the
   right choice. "Use when: you know the html id…", "Use when: no
   specific tool fits — last resort…"
2. **Output (what the return unlocks)** — what the caller does with the
   return value. "Returns `{found, tag, …}` you branch on — pair with
   `click_by_html_id` to act."

Why: LLMs ranking tools glance at the first line only. A pure
description (`"Click an element located by html id, …"`) reads the same
as a lower-level alternative and gives no priority signal. A decision
signal (`"Use when: you already know the html id. Prefer over
click_by_ref when possible."`) tells the LLM when to pick this tool
*and* what to do next. Measured effect on real LLM traces: the
intended tool goes from near-zero uptake to the obvious first choice
for its scenario.

When you add a new tool, write the first line in this shape before
touching anything else. Everything after it (Args / Returns / Example)
can stay conventional.

## Quick Start

```bash
pip install ai-dev-browser
# or pin a specific version
pip install "ai-dev-browser>=0.5,<0.6"
# or with uv
uv add ai-dev-browser
```

Want the unreleased `master` or a specific commit?

```bash
pip install "ai-dev-browser @ git+https://github.com/sudoprivacy/ai-dev-browser.git@master"
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
- **CDP module**: generated from [Google's official CDP spec](https://github.com/ChromeDevTools/devtools-protocol) via [cdp-python](https://github.com/sudoprivacy/cdp-python)

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `AI_DEV_BROWSER_PORT` | Default CDP port (skips auto-detection) |
| `AI_DEV_BROWSER_HEADLESS` | Default headless mode (`1`/`true`) |
| `AI_DEV_BROWSER_REDIRECT` | Block direct CLI, print redirect message |
| `AI_DEV_BROWSER_OUTPUT_DIR` | Default directory for `page_screenshot` (overrides `./screenshots/`). Consumers like sudowork set this to inject a persistent output path so LLMs don't need to learn host-specific conventions. |

## License

AGPL-3.0
