# Real-profile window visibility and input refusal

Investigation of Ladder's `BR-ai-dev-browser-real-profile-hidden-input.md`.

## Findings

The bundled 0.4.3 extension implemented `Browser.getWindowForTarget` but forwarded
`Browser.setWindowBounds` to `chrome.debugger`, where it was unsupported. A live
Chrome 155 reproduction failed on this exact command before sending input.

A second real Windows Chrome window can fully cover the selected automation
window while the latter remains normal and reports `document.hasFocus()=true`.
Chrome then reports genuine `document.visibilityState=hidden`. The neutral-form
reproduction observes this without changing either document property or disabling
native occlusion. This demonstrates a cause of the reported symptom; the exact
cause in the original Google task remains unverified.

The reproduction also exposed a shared typing bug: `_fill_verified` caught the
hidden-page exception, advanced to its native value-setter fallback, and reported
`typed=true, verified=true, method=native`. Visibility refusals now stop before
clearing or focusing a field, and session errors propagate through every typing
rung. A refused positioning move also stops before the click.

## Resulting contract

- Extension 0.4.4 maps window get/set bounds to the supported Chrome window API.
  Both operations require the selected owned tab to belong to that window.
  Revocation during tab lookup prevents a subsequent window mutation.
- `window_set` reports observed window state, document focus, visibility and
  `input_ready`. Focus and visibility are separate observations. A request for
  focus can return `success=false, error_code=unsupported, retryable=false` when
  the page remains hidden. Its runtime hint tells the caller how to recover.
- Actual input preserves `InputUnavailableError` and the original reason. The CLI
  returns semantic exit 6, structured visibility/window/version diagnostics and
  guidance to inspect the selected page before resuming. `input_sent=false` is
  scoped to the withheld dispatch; earlier steps may have completed.
- `browser_connect` reports loaded and bundled extension versions independently.
  It reads the live extension because an older daemon may drop handshake fields.
  A missing loaded version remains null. Python installation metadata never
  stands in for the loaded Chrome extension.

Before resuming a task after an ordinary extension update/reload, inspect its
session and ownership again: reload can reset control. Emulated focus is not
evidence of physical window visibility. Native window APIs are used by the isolated test
fixture to arrange two neutral windows; production has no native-input fallback.

The existing real-profile bridge was probed read-only. Both its bridge status and
live extension diagnostics omitted a loaded version. The original registration
window was left for its existing workflow.

## Acceptance

Local live PTY acceptance on Windows, Python 3.13 and Chrome for Testing 155:

| Workflow | Backends | Result |
| --- | --- | --- |
| Minimize/restore, reject another window, genuinely occlude, refuse Python/CLI input, uncover and submit once | legacy, asyncio | Both passed |
| Load unmodified extension 0.4.3 from the public 0.57.7 wheel, connect with current Python, receive actionable unsupported window result | legacy, asyncio | Both passed |

The generated suites passed all 6 checks, including two import checks, with no
skips. While occluded, refused actions produced no `Input.*` bridge commands,
the field stayed empty, no form-control events occurred, and the HTTP server
received no submission. One recheck observed three trusted keydown events before
the first refused action; their exact origin was not established. All page events
remain in the evidence separately from the dispatch ledger. Afterwards, input and click events were trusted
and exactly one HTTP submission arrived. The final rendered PNG was inspected.

Ladder's existing eight input-policy tests passed against this source checkout.
The Python unit suite passed 241 checks; the JavaScript ownership suite passed
eight. The 63-tool CLI catalog passed its 69 steering contracts; regenerating the
tools changed no wrapper files. The related typing, viewport, mouse and CLI
recovery regression suites passed 26 checks.
Four bridge regression checks also passed. The final traced acceptance is retained
under `scratch/window-traced-acceptance`, including the zero-dispatch evidence.

Scenario JSON files are the source for the generated tests. CI runs the previous
released extension on all three extension matrix entries and native occlusion on
both Windows entries. It retains JSON evidence and the final PNG. Local evidence
is under `scratch/window-visibility-final`; earlier failing runs remain under
`scratch/window-visibility-baseline` and `scratch/window-native-two-windows`.

API references: [Chrome windows](https://developer.chrome.com/docs/extensions/reference/api/windows),
[Chrome tabs](https://developer.chrome.com/docs/extensions/reference/api/tabs).
