# browser CLI

A single, agent-friendly command that wraps ai-dev-browser's ~50 tools as
`browser <noun> <verb> [flags]`. Data goes to stdout, errors to stderr.

## Install

    pip install ai-dev-browser        # installs the `browser` command
    browser --list                    # alias-free: `browser --help` lists nouns

Requires a Chrome/Chromium install for live browsing. The CLI auto-detects a
running Chrome debug port; otherwise start one with `browser session start`.

## Output modes (every command)

- `--json`   machine-readable JSON.
- `--quiet`  just the primary scalar (port, url, path, count, ...).
- `--full`   dump every field (default output is terse: ~3-4 fields/item).
- `--no-interactive`  never prompt; missing required values error out.

When stdout is not a TTY (piped/redirected), `--json --quiet --no-interactive`
are auto-enabled, so output is always pipe-safe and never hangs.

## Discover commands

    browser --help                 # list nouns
    browser page --help            # list verbs under `page`
    browser page goto --help       # flags for one command (from the signature)

## 5 most-used commands

    # 1. Start (or reuse) a browser — idempotent: reuses an idle Chrome by default
    browser session start --json
    browser session start --headless --json

    # 2. Navigate
    browser page goto --url https://example.com --json

    # 3. See what's interactable (returns refs for click/type by ref)
    browser page discover --json

    # 4. Click / type
    browser click text --text "Sign in" --json
    browser type text --text "hello" --selector "#search" --json

    # 5. List sessions / tabs
    browser session list --json
    browser tab list --json

## Exit codes

`0` ok · `2` validation (bad/missing flag) · `4` not-found (element or no
browser) · `5` conflict · `7` auth · `8` rate-limit · `9` transient (timeout,
connection). Never `1` for everything — branch on the code.

In `--json` mode an error is printed to **stderr** as:

    {"error": {"code": 4, "message": "...", "retryable": true, "hint": "..."}}

## Common error recoveries

- `code 4` + "Failed to connect to Chrome" → no browser running. Run
  `browser session start` first (retryable).
- `code 4` + "not found" → the element/target isn't there. Re-run
  `browser page discover` and use a fresh `--ref`, or widen your selector.
- `code 9` + "timeout" → bump `--timeout`, or `browser page wait-ready`
  before acting; then retry.

## Notes

- Noun-verb tree: session, page, tab, click, find, type, element, mouse,
  cookies, storage, window, js, cdp, dialog, download, login.
- `browser login interactive` is human-in-the-loop; it fails fast (code 7)
  under `--no-interactive` or when stdout is not a TTY.
- This CLI is additive. The per-tool modules
  (`python -m ai_dev_browser.tools.page_goto`) and the
  `ai_dev_browser.core` Python API are unchanged.
