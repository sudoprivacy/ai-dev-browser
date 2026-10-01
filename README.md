# ai-dev-browser

A browser for AI to develop web automation — human-like automation that works seamlessly in a world designed for humans.

## What is this?

**ai-dev-browser is a browser that AI agents (Claude, GPT, etc.) use to see and interact with web pages** — similar to how [Claude in Chrome](https://claude.com/chrome) works, but headless-compatible and embeddable.

Ways to inspect and capture pages:

- **Accessibility tree** (`page_discover`): semantic element discovery with refs for clicking/typing
- **Screenshots** (`page_screenshot` + `mouse_click --screenshot`): visual coordinate-based interaction with automatic scaling
- **Interaction recordings** (`page_record_start` / `page_record_stop`): record a tab across CLI calls and save a shareable animated GIF

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
[cli-steering-engineering](https://github.com/sudoprivacy/cli-steering-engineering) for the
underlying decorator.

Tools cover: navigation, element interaction, mouse, tabs, screenshots, recordings,
cookies, storage, window management, dialogs, downloads, and raw CDP.
To see the current list (count and names change — this README
deliberately doesn't pin them):

```bash
ls ai_dev_browser/tools/
```

**One file per CLI command, by design.** Each CLI command gets its own
`tools/<name>.py` (e.g. `tools/click_by_text.py`, `tools/click_by_xpath.py`).
Our invocation is `python -m ai_dev_browser.tools.<name>` — one file
1:1 maps to one CLI path with no extra subcommand layer. The
`<verb>_by_<spec>` family (`click_by_text`, `click_by_ref`, `click_by_html_id`,
`click_by_xpath`) clusters alphabetically under `ls`, so domain navigation is
preserved without grouping into a single file. Auto-generation reinforces
the pattern: `tools/_generate.py` produces exactly one wrapper per
core function in `__all__`, no manual subcommand routing.

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
| `page_*`    | `page_goto`, `page_reload`, `page_screenshot`, `page_record_start`, `page_record_stop`, `page_discover`, `page_scroll`, `page_wait_ready`, `page_wait_url`, `page_wait_element`, `page_info`, `page_html`, `page_emulate_focus` |
| `tab_*`     | `tab_new`, `tab_close`, `tab_list`, `tab_switch`    |
| `cookies_*` | `cookies_extract_live`, `cookies_extract_offline`, `cookies_import`, `cookies_save`, `cookies_load` |
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
# or upgrade an existing installation
pip install --upgrade ai-dev-browser
# or with uv
uv add ai-dev-browser
```

Want the unreleased `master` or a specific commit?

```bash
pip install "ai-dev-browser @ git+https://github.com/sudoprivacy/ai-dev-browser.git@master"
```

### Discover tools

Core docstrings supply CLI help, including parameter types, defaults and
usage guidance. Start with the file listing and read the relevant tool's help:

```bash
# What tools exist
ls ai_dev_browser/tools/

# How to use any one of them (docstring first line is a decision
# signal: "Use when: … Returns {…} so you can …")
python -m ai_dev_browser.tools.page_discover --help
python -m ai_dev_browser.tools.click_by_text --help
python -m ai_dev_browser.tools.browser_start --help

# Share a GIF demo or before/after recording of a workflow
python -m ai_dev_browser.tools.page_record_start --help
python -m ai_dev_browser.tools.page_record_stop --help
```

For runnable end-to-end workflows, the integration tests in
[`tests/integration/`](tests/integration/) are the canonical
reference — they always match the current API because CI runs them on
every commit. Start with
[`test_locator_workflows.py`](tests/integration/test_locator_workflows.py)
for common `page_goto` → `click_by_*` / `find_by_*` → `page_screenshot`
patterns.

### Live browser acceptance

The CLI and real extension regression workflows in
[`test_cli_extension_workflows.py`](tests/integration/test_cli_extension_workflows.py)
run in CI. Public-site acceptance is also available in
[`test_public_web_workflows.py`](tests/integration/test_public_web_workflows.py):
search Wikipedia through CLI subprocesses, then drive its language menu through
the real extension and continue after restarting the extension worker.

To run public-site acceptance locally (PowerShell):

```powershell
uv sync --extra dev
$env:AI_DEV_BROWSER_LIVE_WEB = '1'
$env:AI_DEV_BROWSER_TEST_EXTENSION_CHROME = 'C:\path\to\chrome-for-testing\chrome.exe'
uv run python -m pytest -v -s tests/integration/test_public_web_workflows.py --basetemp scratch/public-web-acceptance
```

Use a Chrome for Testing or Chromium executable that supports loading unpacked
extensions. The tests launch temporary browser profiles and close them afterward.
No login or API key is needed. Public-site tests are opt-in because they depend
on internet access and Wikipedia's current UI; once enabled, failures are reported
normally. Screenshots and `evidence.json` files stay under the selected
`--basetemp` directory for review (pytest clears that directory on each run).

Both workflow files are generated from the adjacent `scenarios_*.json` sources
using `integration-test-generator`; edit the scenarios and regenerate the tests.

### Record an interaction

```bash
python -m ai_dev_browser.tools.page_record_start --port 9222 --fps 10 --out output/before.gif
# Continue with page_discover, click_by_ref, type_by_ref, page_goto, etc.
python -m ai_dev_browser.tools.page_record_stop
```

Start returns a `recording_id` after the first frame arrives. Stop without an ID
selects the single unfinished recording started in the current working directory.
For concurrent recordings or a different directory, use
`page_record_stop --recording-id <id>`. Stop works even if the browser has closed:
an interrupted recording returns an error instead of a partial success.

The recorder runs in a detached process, so CLI exit and Python client disconnect
do not stop capture. The Python API uses the same names and arguments:
`await page_record_start(tab, out="before.gif")`, then
`await page_record_stop(recording_id)`. Use `--transport extension` on **start**
to record through the real extension. Keep that tab visible; switching tabs does
not switch the recording. After upgrading an already running bridge, restart it
with `browser_disconnect` / `browser_connect --transport extension` and reload
the extension to pick up concurrent event delivery and detach reporting.

Output is a looping GIF of the viewport, scaled to fit 1280×720, without audio
or the OS cursor. No ffmpeg installation is needed. Idle time is preserved;
`--fps` caps frame sampling (1–30, default 10). GIF uses a 256-color palette per
frame. The safety limit is 300 seconds (`--max-duration`, 1–600) and 10 MB:
stop before the limit to save. Closing the tab, losing the extension, failing an
ACK, exceeding a limit, or failing a file write invalidates the recording.
Only successful stop publishes the final path; existing files are never replaced.
Successful output includes frame count, duration, dimensions and file size.
The file cap fits Feishu's [documented GIF preview limit](https://www.feishu.cn/hc/en-US/articles/360049067549-size-and-format-requirements-for-uploading-or-previewing-files).
For busy pages that exceed it, lower `--fps` or record a shorter interaction.

Recording state and diagnostic logs live in `~/.ai-dev-browser/recordings`
(`AI_DEV_BROWSER_RECORDING_DIR` overrides this). The output directory honors
`AI_DEV_BROWSER_OUTPUT_DIR`. A killed process may leave a hidden `.partial`
file, which is not a completed recording.

The generated [recording workflows](tests/integration/test_recording_workflows.py)
exercise real CLI processes and the real extension, decode every GIF frame, and
check the visible states in order, elapsed time, and interrupted recordings.
They run in CI. To run locally and retain GIFs and decoded frames:

```powershell
$env:AI_DEV_BROWSER_TEST_EXTENSION_CHROME = 'C:\path\to\chrome-for-testing\chrome.exe'
uv run python -m pytest -v -s tests/integration/test_recording_workflows.py --basetemp scratch/recording-acceptance
```

Edit `tests/integration/scenarios_recording.json` and regenerate with
`integration-test-generator` when changing these scenarios.

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
| `AI_DEV_BROWSER_OUTPUT_DIR` | Default directory for screenshots and recordings (overrides `./output/`). Consumers like sudowork can set a persistent output path. |
| `AI_DEV_BROWSER_RECORDING_DIR` | Recording state and worker logs (default `~/.ai-dev-browser/recordings`). |

## Releases

Published versions are available on [PyPI](https://pypi.org/project/ai-dev-browser/)
and [GitHub Releases](https://github.com/sudoprivacy/ai-dev-browser/releases).
Each GitHub release includes the same wheel and source distribution sent to PyPI,
the bundled Chrome extension as an unpackable ZIP, and `SHA256SUMS`.
For extension mode, extract the ZIP and load its directory in `chrome://extensions`.
After upgrading, reload the extension and restart an already running bridge.

Maintainers: run live browser acceptance and wait for CI on the release commit.
Create an annotated `vX.Y.Z` tag whose message contains the release notes, then push
that tag. The [publish workflow](.github/workflows/publish.yml) derives the Python
version from the tag, builds and validates both distributions, publishes to PyPI,
and creates the GitHub Release with the matching assets and tag notes. Verify a
fresh PyPI installation with the live recording workflow before closing a release.

## License

AGPL-3.0
