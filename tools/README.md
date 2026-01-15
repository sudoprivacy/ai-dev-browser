# nodriver-kit Tools

AI-friendly CLI tools for browser automation. Each tool is standalone and outputs JSON.

## Quick Reference

| Tool | Purpose | Key Args |
|------|---------|----------|
| `browser_start.py` | Start Chrome | `--port`, `--headless` |
| `browser_list.py` | List running browsers | - |
| `page_goto.py` | Navigate to URL | `--url`, `--wait` |
| `page_screenshot.py` | Take screenshot | `--output`, `--full` |
| `page_html.py` | Get page HTML | `--selector`, `--output` |
| `element_find.py` | Find elements | `--text`, `--selector` |
| `element_click.py` | Click element | `--text`, `--selector` |
| `element_type.py` | Type into input | `--selector`, `--text` |
| `js_execute.py` | Run JavaScript | `--code` |
| `cookies_save.py` | Save cookies | `--output`, `--pattern` |
| `cookies_load.py` | Load cookies | `--input` |
| `login_interactive.py` | Manual login helper | `--url`, `--pattern` |

## Common Options

- `--port`, `-p`: Chrome debugging port (default: 9222)
- Output is JSON for easy parsing

## Usage Examples

```bash
# Start browser
python tools/browser_start.py
# {"port": 9222, "pid": 12345, "message": "Browser started on port 9222"}

# Navigate
python tools/page_goto.py --url "https://example.com"
# {"url": "https://example.com/", "title": "Example Domain"}

# Screenshot (AI can then Read the file)
python tools/page_screenshot.py --output /tmp/page.png
# {"path": "/tmp/page.png", "message": "Screenshot saved"}

# Find elements
python tools/element_find.py --text "Login"
# {"found": true, "count": 1, "elements": [{"tag": "button", "text": "Login"}]}

# Click
python tools/element_click.py --text "Login"
# {"clicked": true, "message": "Clicked element"}

# Type
python tools/element_type.py --selector "input[name=email]" --text "user@example.com"
# {"typed": true, "text": "user@example.com"}

# Execute JS
python tools/js_execute.py --code "document.title"
# {"result": "Example Domain", "type": "str"}

# Save cookies
python tools/cookies_save.py --pattern "example"
# {"path": "~/.nodriver-kit/cookies.dat", "message": "Cookies saved"}

# Interactive login (for AI: call this when no valid session)
python tools/login_interactive.py --url "https://example.com/login"
# Opens browser, waits for manual login, saves cookies when browser closes
```

## For AI Agents

1. **Start browser**: `browser_start.py`
2. **Navigate**: `page_goto.py --url "..."`
3. **Inspect**: `page_screenshot.py` then Read the image
4. **Find elements**: `element_find.py --text "..."`
5. **Interact**: `element_click.py`, `element_type.py`
6. **Get data**: `js_execute.py --code "..."`
7. **Handle login**: `login_interactive.py --url "..."` (human completes login)
