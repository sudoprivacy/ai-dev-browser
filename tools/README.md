# nodriver-kit Tools

AI-friendly CLI tools for browser automation. Each tool is standalone and outputs JSON.

Superset of [nodriver](https://github.com/nicedoctor/nodriver) native methods + [dev-browser](https://github.com/SawyerHood/dev-browser) features.

## Quick Reference

### Browser Management
| Tool | Purpose | Key Args |
|------|---------|----------|
| `browser_start.py` | Start Chrome | `--port`, `--headless` |
| `browser_stop.py` | Stop Chrome | `--port`, `--all` |
| `browser_list.py` | List running browsers | - |

### Tab Management
| Tool | Purpose | Key Args |
|------|---------|----------|
| `tab_list.py` | List all tabs | - |
| `tab_new.py` | Open new tab | `--url` |
| `tab_switch.py` | Switch to tab | `--id` |
| `tab_close.py` | Close tab | `--id` |

### Page Navigation
| Tool | Purpose | Key Args |
|------|---------|----------|
| `page_goto.py` | Navigate to URL | `--url`, `--wait` |
| `page_reload.py` | Reload/back/forward | `--back`, `--forward` |
| `page_wait.py` | Wait for page ready | `--idle`, `--sleep` |
| `page_info.py` | Get URL/title/state | - |
| `wait_url.py` | Wait for URL pattern | `--pattern`, `--exact` |

### Page Content
| Tool | Purpose | Key Args |
|------|---------|----------|
| `page_screenshot.py` | Take screenshot | `--output`, `--full` |
| `page_html.py` | Get page HTML | `--selector`, `--output` |
| `page_snapshot.py` | **AI snapshot** (accessibility tree) | `--interactable`, `--format` |

### Element Interaction
| Tool | Purpose | Key Args |
|------|---------|----------|
| `element_find.py` | Find by text/selector | `--text`, `--selector` |
| `element_xpath.py` | Find by XPath | `--xpath` |
| `element_click.py` | Click element | `--text`, `--selector` |
| `element_type.py` | Type into input | `--selector`, `--text`, `--clear` |
| `element_scroll.py` | Scroll page | `--top`, `--bottom`, `--y` |
| `element_wait.py` | Wait for element | `--text`, `--selector`, `--timeout` |

### Mouse Control
| Tool | Purpose | Key Args |
|------|---------|----------|
| `mouse_move.py` | Move mouse | `--x`, `--y` |
| `mouse_click.py` | Click at coordinates | `--x`, `--y`, `--button` |
| `mouse_drag.py` | Drag from A to B | `--from-x/y`, `--to-x/y` |

### Window Control
| Tool | Purpose | Key Args |
|------|---------|----------|
| `window_resize.py` | Resize window | `--width`, `--height` |
| `window_state.py` | Maximize/minimize | `--maximize`, `--fullscreen` |

### JavaScript & Data
| Tool | Purpose | Key Args |
|------|---------|----------|
| `js_execute.py` | Run JavaScript | `--code` |
| `cdp_send.py` | Send CDP command | `--method`, `--params` |

### Storage
| Tool | Purpose | Key Args |
|------|---------|----------|
| `storage_get.py` | Get localStorage | `--key` |
| `storage_set.py` | Set localStorage | `--key`, `--value`, `--json` |

### Cookies & Session
| Tool | Purpose | Key Args |
|------|---------|----------|
| `cookies_save.py` | Save cookies | `--output`, `--pattern` |
| `cookies_load.py` | Load cookies | `--input` |
| `cookies_list.py` | List cookies | `--domain` |
| `login_interactive.py` | Manual login | `--url`, `--pattern` |

### Download
| Tool | Purpose | Key Args |
|------|---------|----------|
| `download_path.py` | Set download dir | `--path` |
| `download_file.py` | Download file | `--url`, `--output` |

### Security
| Tool | Purpose | Key Args |
|------|---------|----------|
| `cf_verify.py` | Cloudflare bypass | - |

## Common Options

- `--port`, `-p`: Chrome debugging port (default: 9222)
- All output is JSON for easy parsing

## The Most Important Tool: `page_snapshot.py`

This is the **key AI feature** - returns an accessibility tree instead of raw HTML:

```bash
python tools/page_snapshot.py --interactable
```

Output:
```json
{
  "snapshot": [
    {"ref": "1", "role": "link", "name": "Home"},
    {"ref": "2", "role": "button", "name": "Sign in"},
    {"ref": "3", "role": "textbox", "name": "Email", "focused": true},
    {"ref": "4", "role": "heading", "name": "Welcome", "level": 1}
  ],
  "count": 4
}
```

**Why this matters:**
- Raw HTML has CSS classes, nested divs, scripts → noise for AI
- Accessibility tree has semantic info (role, name, state) → AI-friendly
- Use `--interactable` to only show buttons, links, inputs

## Usage Examples

```bash
# Start browser
python tools/browser_start.py

# Navigate and get AI-friendly snapshot
python tools/page_goto.py --url "https://example.com"
python tools/page_snapshot.py --interactable
# Returns semantic structure AI can understand

# Click by text (easiest)
python tools/element_click.py --text "Sign in"

# Or use XPath for complex queries
python tools/element_xpath.py --xpath "//button[@type='submit']"

# Type into input
python tools/element_type.py --selector "input[name=email]" --text "user@example.com"

# Wait for URL to change (SPA navigation)
python tools/wait_url.py --pattern "/dashboard"

# Multi-tab workflow
python tools/tab_new.py --url "https://other-site.com"
python tools/tab_list.py
python tools/tab_switch.py --id 0

# Screenshot for visual verification
python tools/page_screenshot.py --output /tmp/page.png

# Cloudflare bypass (requires opencv-python)
python tools/cf_verify.py

# Stop browser
python tools/browser_stop.py
```

## For AI Agents

### Recommended Flow
1. `browser_start.py` - Start browser
2. `cookies_load.py` - Load saved session
3. `page_goto.py` - Navigate
4. `page_snapshot.py --interactable` - **Get AI-friendly view**
5. `element_click.py` / `element_type.py` - Interact
6. `wait_url.py` - Wait for navigation
7. `page_snapshot.py` - Check new state
8. `cookies_save.py` - Save session
9. `browser_stop.py` - Close

### When Login Required
```bash
python tools/login_interactive.py --url "https://example.com/login"
```
Opens browser for human login. Cookies saved automatically.

### CDP for Advanced Operations
```bash
# Emulate mobile device
python tools/cdp_send.py --method "Emulation.setDeviceMetricsOverride" \
  --params '{"width": 375, "height": 812, "deviceScaleFactor": 3, "mobile": true}'
```

Reference: https://chromedevtools.github.io/devtools-protocol/
