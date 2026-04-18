# ai-dev-browser

A browser for AI to develop web automation — human-like automation that works seamlessly in a world designed for humans.

## What is this?

**ai-dev-browser is a browser that AI agents (Claude, GPT, etc.) use to see and interact with web pages** — similar to how [Claude in Chrome](https://claude.com/chrome) works, but headless-compatible and embeddable.

Two interaction modes:
- **Accessibility tree** (`page_discover`): semantic element discovery with refs for clicking/typing
- **Screenshots** (`page_screenshot` + `mouse_click --screenshot`): visual coordinate-based interaction with automatic scaling

```bash
# AI discovers elements
python -m ai_dev_browser.tools.page_discover

# AI clicks by ref (from accessibility tree)
python -m ai_dev_browser.tools.click_by_ref --ref "5#214"

# AI clicks by coordinates (from screenshot)
python -m ai_dev_browser.tools.mouse_click --x 105 --y 52 --screenshot screenshots/page.png
```

## Screenshot Coordinate Alignment

Screenshots are auto-scaled to fit LLM vision limits (default 1280px
long edge for Claude; configurable per model). Scaling metadata is
embedded in the PNG, so when a mouse tool accepts `--screenshot`,
coordinates you read off the image are auto-converted back to CSS
viewport space. See
`python -m ai_dev_browser.tools.page_screenshot --help` for the limits
and `--help` on any mouse tool for the coord passthrough.

## CLI = Python (SSOT)

Every tool is exposed two ways, same signature, from one core function
definition — CLI wrappers are auto-generated. Pick whichever is more
convenient:

- **CLI**: `python -m ai_dev_browser.tools.<name> [flags]`
- **Python**: `from ai_dev_browser.core import <name>`

Because both paths are generated from a single source, parameter
changes flow to both at once and can't drift. See
[cli-args-ssot](https://github.com/sudoprivacy/cli-args-ssot) for the
underlying decorator.

Tools cover: navigation, element interaction, mouse, tabs, screenshots,
cookies, storage, window management, dialogs, downloads, raw CDP, and
Cloudflare bypass. To see the current list (count and names change —
this README deliberately doesn't pin them):

```bash
ls ai_dev_browser/tools/
```

### Tool Naming Convention

Two patterns, consistent across the entire toolkit (CLI file names,
Python exports, and docstring titles all match):

**1. Domain-scoped operations: `<domain>_<verb>`**

The noun comes first. Operations that act on a "thing" (browser
lifecycle, page state, cookie store, tabs, storage, mouse, etc.) all
sort together in `ls tools/` and tab completion:

| Domain      | Examples                                            |
|-------------|-----------------------------------------------------|
| `browser_*` | `browser_start`, `browser_stop`, `browser_list`     |
| `page_*`    | `page_goto`, `page_reload`, `page_screenshot`, `page_discover`, `page_scroll`, `page_wait_ready`, `page_wait_url`, `page_wait_element`, `page_info`, `page_html`, `page_emulate_focus` |
| `tab_*`     | `tab_new`, `tab_close`, `tab_list`, `tab_switch`    |
| `cookies_*` | `cookies_save`, `cookies_load`, `cookies_list`      |
| `storage_*` | `storage_get`, `storage_set`                        |
| `mouse_*`   | `mouse_click`, `mouse_move`, `mouse_drag`           |
| `dialog_*`  | `dialog_respond`                                    |
| `window_*`  | `window_set`                                        |
| `cdp_*`     | `cdp_send`                                          |

**2. Element-targeting operations: `<verb>_by_<spec>`**

The verb comes first; the spec is how you identify the element. LLM
mental model: "I have an X, I want to do Y → look for `Y_by_X`."

| Spec        | Source                                        | Example             |
|-------------|-----------------------------------------------|---------------------|
| `_by_ref`   | ref returned by `page_discover` (AX tree)     | `click_by_ref`      |
| `_by_text`  | visible text content                          | `click_by_text`     |
| `_by_html_id` | `id="..."` HTML attribute (cross-frame)     | `click_by_html_id`  |
| `_by_xpath` | XPath expression (`document.evaluate`)        | `click_by_xpath`    |

Verbs currently in use: `click`, `type`, `focus`, `hover`, `drag`,
`highlight`, `html` (read), `screenshot`, `select`, `upload`, `find`.

`page_discover` is the broad catalog (pattern 1, domain-scoped);
`find_by_*` is single-element targeted lookup (pattern 2,
element-targeting). Pick `find_by_*` when you know the id / xpath /
unique text; pick `page_discover` when you don't yet.

Outliers (by design, not oversight): `download` (standalone verb, no
domain fits), `js_evaluate` (last-resort escape hatch), `login_interactive`
(explicit marker that this flavor needs human input, unlike scripted
login flows you'd build on `page_goto` + `type_by_text`).

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

### Discovery (no hand-written example to drift)

The source IS the documentation — README intentionally does not
duplicate function signatures or runnable workflows, so it can't
rot when things get renamed. Instead:

```bash
# What tools exist
ls ai_dev_browser/tools/

# How to use any one of them (docstring first line is a decision
# signal: "Use when: … Returns {…} so you can …")
python -m ai_dev_browser.tools.page_discover --help
python -m ai_dev_browser.tools.click_by_text --help
python -m ai_dev_browser.tools.browser_start --help
```

For runnable end-to-end workflows, the integration tests in
[`tests/integration/`](tests/integration/) are the canonical
reference — they always match the current API because CI runs them on
every commit. Start with
[`test_locator_workflows.py`](tests/integration/test_locator_workflows.py)
for common `page_goto` → `click_by_*` / `find_by_*` → `page_screenshot`
patterns.

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
