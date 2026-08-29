# AI Dev Browser — bridge extension

This lets **ai-dev-browser drive your *real* Chrome** (your profile, logins, and
device-trust) via `chrome.debugger` over a local bridge — the "extension
transport". Use it when automation needs your real logged-in session (Google
SSO, sites that block fresh profiles). For autonomous/headless/CI work, the
default CDP mode (`browser_start`) is better.

## Loading it (one-time, manual)

Chrome 127+ blocks command-line extension loading, so this is loaded by hand
once:

1. Open `chrome://extensions`
2. Turn on **Developer mode** (top-right)
3. Click **Load unpacked** and select **this folder** (the one containing
   `manifest.json`)
4. Keep the extension **enabled** and Chrome **running**

Then run any ai-dev-browser tool with `--transport extension` (or set
`AI_DEV_BROWSER_TRANSPORT=extension`).

## What it does / doesn't

- Only active while ai-dev-browser is connected; it attaches `chrome.debugger`
  to the active tab and relays CDP, then detaches.
- The "扩展正在调试此浏览器 / extension is debugging this browser" banner is
  Chrome's mandatory consent notice for `chrome.debugger`. It is **browser UI,
  invisible to web pages** — it does not affect bot detection.
- It never decrypts cookies or bypasses any Chrome protection; it drives the
  browser through the sanctioned, user-permissioned extension API.
