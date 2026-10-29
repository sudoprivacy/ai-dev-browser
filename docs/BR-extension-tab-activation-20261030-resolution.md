# Extension activation: real visibility and daemon diagnostics

## Finding and limits

The existing activation sequence already selects the owned tab, restores a
minimized window, requests Chrome window focus and calls `Page.bringToFront`.
It continues to wait up to two seconds for genuine document visibility.

On Windows, a second topmost Chrome window can cover a normal active automation
window while its document and Chrome window both report focused. The page still
reports `visibility=hidden`. Removing that known fixture cover restores trusted
input on the same target. This reproduces the reported state, but does **not**
establish the native cause of the original user-profile incident.

Chromium documents [native window occlusion tracking](https://chromium.googlesource.com/chromium/src/+/master/docs/windows_native_window_occlusion_tracking.md).
The extension [window API](https://developer.chrome.com/docs/extensions/reference/api/windows)
reports logical focus/state; it does not identify whether a native cover, locked
desktop or virtual desktop caused the document's hidden state. No additional
activation call is justified by the observed neutral-fixture results.

## Changes

- Extension 0.4.9 adds selected owned tab/window observations to the existing
  diagnostic route. It checks ownership across asynchronous reads and refuses
  to report the wrong window when a tab moves. It returns no other tab URLs or
  titles in the selected-page observation.
- `window_set` and hidden-input errors share these observations:
  `tab_active`, `window_focused`, `window_state`, `window_id`, and
  `window_observed_at` (Unix milliseconds). `focused` retains its existing
  meaning, document focus. Older workers return null for unknown focus/activity.
- `window_set(focus=True)` checks observed Chrome window focus when available,
  alongside genuine page visibility. `input_ready` describes visibility
  separately. A hidden result remains `success=false`, `unsupported`,
  `retryable=false`; soft-result CLI exit conventions are preserved.
- Input refusal hints tell an agent to inspect these distinct states and ask
  the human to show/uncover the same window on the current unlocked desktop.
  They do not claim to know the native cause. No input, visibility spoofing,
  target adoption, transport fallback or automatic replay was added.
- The Python bridge's existing status route reports its own imported SDK
  version, start time (Unix seconds), configured message limit (bytes), and
  active controller **socket** count. Browser/page sockets count; status/control
  probes do not. `browser_connect` returns this pre-connect snapshot separately
  from extension versions. An older daemon remains unknown. Runtime mismatch
  guidance requires coordinating controllers before explicit disconnect/connect;
  no automatic restart or termination of another driver's bridge was added.

The original disconnection's exact WebSocket cause remains unproven because the
old daemon had no retained close evidence. Reloading a Chrome extension does
not upgrade Python code already running in the bridge process.

## Acceptance and CLI steering

Live PTY acceptance uses isolated Windows Chrome for Testing 156.0.8078.73,
real bundled extension, normal sandbox and native occlusion enabled. Both legacy
and asyncio WebSocket server implementations exercise the same neutral form:

1. Connect and inspect the actual running daemon.
2. Minimize/restore the owned window; activate its inactive tab without adopting
   the unrelated selected tab; focus a normal unfocused window.
3. Cover only the fixture window. Observe active/focused/normal **and hidden**;
   refuse Python and CLI mouse/keyboard actions. Assert zero `Input.*` dispatch,
   empty form and zero server submissions.
4. Uncover the same target, type and click with trusted events, assert exactly
   one HTTP receipt, inspect the final PNG, and preserve unrelated tab IDs/URLs.

The ordinary unfocused-window case uses Chrome APIs without native topmost
assistance. Additional live runs observed both true and false Chrome window
focus under the known cover; the cover does not guarantee foreground focus.
The regression requires a real boolean observation and hidden-input refusal in
both cases. The two-second production visibility deadline remains unchanged.

The scenario source is `tests/integration/scenarios_extension_window.json`;
the integration-test-generator skill generates its test entry. The existing
Windows CI job runs this suite and retains JSON/PNG evidence. Real WebSocket
regressions additionally verify daemon version and controller counting on both
server implementations, including a probe socket becoming a CDP driver later.

The cli-steering-engineering audit keeps core docstrings as help/return/failure
SSOT. `window_set --help` advertises activation and its ready-state return;
runtime refusal hints carry recovery. `browser_connect --help` distinguishes
the running bridge from the extension and installed client. No additional tool
or duplicate CLI arguments were introduced. Catalog steering contracts and
generated-wrapper consistency are checked alongside the live CLI refusals.

Local results: the native suite passed three checks (two browser journeys and
one import check); Python unit/bridge regressions passed 329 checks, JavaScript
ownership checks passed 25, and the CLI audit passed 119. Regenerating all 63
CLI wrappers changed none. The no-extension bridge test invokes the actual CLI
against a live daemon and retains truthful runtime diagnostics on failure.
An isolated daemon from the unchanged public 0.57.7 package was also queried by
the new CLI: runtime version, message limit and driver count stayed null, an
actionable warning appeared, and the daemon remained running until its test
owner explicitly stopped it. No version was inferred from the newer client.

Original-profile retesting is still needed to identify that incident's native
condition. The fix makes that next refusal observable; it does not claim that
Chrome focus APIs can force every Windows desktop condition to become visible.
