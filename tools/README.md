# nodriver-kit Tools

AI-friendly CLI tools for browser automation. Each tool is standalone and outputs JSON.

## Quick Reference

### Browser Management
| Tool | Purpose | Key Args |
|------|---------|----------|
| `browser_start.py` | Start Chrome | `--port`, `--headless` |
| `browser_stop.py` | Stop Chrome | `--port`, `--all` |
| `browser_list.py` | List running browsers | - |

### Page Navigation
| Tool | Purpose | Key Args |
|------|---------|----------|
| `page_goto.py` | Navigate to URL | `--url`, `--wait` |
| `page_reload.py` | Reload/back/forward | `--back`, `--forward` |
| `page_wait.py` | Wait for page ready | `--idle`, `--sleep` |
| `page_screenshot.py` | Take screenshot | `--output`, `--full` |
| `page_html.py` | Get page HTML | `--selector`, `--output` |

### Element Interaction
| Tool | Purpose | Key Args |
|------|---------|----------|
| `element_find.py` | Find elements | `--text`, `--selector` |
| `element_click.py` | Click element | `--text`, `--selector` |
| `element_type.py` | Type into input | `--selector`, `--text`, `--clear` |
| `element_scroll.py` | Scroll on page | `--to`, `--selector`, `--y`, `--top`, `--bottom` |
| `element_wait.py` | Wait for element | `--text`, `--selector`, `--timeout` |

### JavaScript & Data
| Tool | Purpose | Key Args |
|------|---------|----------|
| `js_execute.py` | Run JavaScript | `--code` |
| `cdp_send.py` | Send CDP command | `--method`, `--params` |

### Cookies & Session
| Tool | Purpose | Key Args |
|------|---------|----------|
| `cookies_save.py` | Save cookies to file | `--output`, `--pattern` |
| `cookies_load.py` | Load cookies from file | `--input` |
| `cookies_list.py` | List current cookies | `--domain` |
| `login_interactive.py` | Manual login helper | `--url`, `--pattern` |

## Common Options

- `--port`, `-p`: Chrome debugging port (default: 9222)
- All output is JSON for easy parsing

## Usage Examples

```bash
# Start browser
python tools/browser_start.py
# {"port": 9222, "pid": 12345, "message": "Browser started"}

# Navigate
python tools/page_goto.py --url "https://example.com"
# {"url": "https://example.com/", "title": "Example Domain"}

# Wait for page
python tools/page_wait.py --idle
# {"ready": true, "state": "complete"}

# Screenshot (AI can then Read the file)
python tools/page_screenshot.py --output /tmp/page.png
# {"path": "/tmp/page.png"}

# Find elements
python tools/element_find.py --text "Login"
# {"found": true, "count": 1, "elements": [...]}

# Wait for element to appear
python tools/element_wait.py --text "Success" --timeout 30
# {"found": true, "elapsed": 2.5}

# Click
python tools/element_click.py --text "Login"
# {"clicked": true}

# Type
python tools/element_type.py --selector "input[name=email]" --text "user@example.com" --clear
# {"typed": true}

# Scroll
python tools/element_scroll.py --bottom
# {"scrolled": true, "message": "Scrolled to bottom"}

# Execute JS
python tools/js_execute.py --code "document.title"
# {"result": "Example Domain"}

# Send CDP command
python tools/cdp_send.py --method "Network.getCookies"
# {"method": "Network.getCookies", "result": {...}}

# List cookies
python tools/cookies_list.py --domain "example.com"
# {"cookies": [...], "count": 5}

# Save cookies
python tools/cookies_save.py --pattern "example"
# {"path": "~/.nodriver-kit/cookies.dat"}

# Stop browser
python tools/browser_stop.py
# {"stopped": true, "port": 9222}

# Interactive login (for AI: when no valid session)
python tools/login_interactive.py --url "https://example.com/login"
# Opens browser, waits for manual login, saves cookies
```

## For AI Agents

### Basic Flow
1. `browser_start.py` - Start browser
2. `cookies_load.py` - Load saved session (if exists)
3. `page_goto.py --url "..."` - Navigate
4. `page_wait.py --idle` - Wait for page
5. `page_screenshot.py` - Take screenshot, then Read to see page
6. `element_find.py` - Find elements
7. `element_click.py` / `element_type.py` - Interact
8. `js_execute.py` - Get data via JavaScript
9. `cookies_save.py` - Save session for next time
10. `browser_stop.py` - Close browser

### When Login Required
If you detect no valid session:
```bash
python tools/login_interactive.py --url "https://example.com/login" --pattern "example"
```
This opens browser and waits for human to complete login. Cookies are saved automatically when browser is closed.

### CDP for Advanced Operations
Use `cdp_send.py` for anything not covered by other tools:
```bash
# Get all cookies with full details
python tools/cdp_send.py --method "Network.getAllCookies"

# Emulate device
python tools/cdp_send.py --method "Emulation.setDeviceMetricsOverride" \
  --params '{"width": 375, "height": 812, "deviceScaleFactor": 3, "mobile": true}'

# Clear browser cache
python tools/cdp_send.py --method "Network.clearBrowserCache"
```

Reference: https://chromedevtools.github.io/devtools-protocol/
