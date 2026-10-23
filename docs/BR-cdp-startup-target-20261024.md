# CDP startup target ownership — 2026-10-24

## Observed failure

The post-merge Windows remote-view job for PR #37 failed four first-navigation
workflows on Chrome for Testing 156.0.8078.47. Navigation returned
"net::ERR_ABORTED", and read-only inspection found "about:blank". Both controlled
startup-race fixtures also failed while preparing their neutral starting page.

Failed run: https://github.com/sudoprivacy/ai-dev-browser/actions/runs/39992205855

The earlier PR job used the same Chrome version and passed. A local run of the
unchanged Windows workflow passed 23 checks with six existing conditional skips.
These results show that ordinary repetition alone does not establish a fix.

## Change

Fresh CDP launches establish the browser identity, create one owned target through
the existing CDP transport, and retain the returned target ID. Chrome starts with
the standard no-startup-window switch; the requested URL is supplied to that one
target creation. The initial page is created within the existing startup timeout.

If the creation reply is lost, startup retains the Chrome process and its ownership
record, returns a transient failure, and directs the caller to reconnect and
inspect current pages. It issues no second creation or navigation.

The locale observation reads the created target explicitly. Reuse, connection,
extension startup, page navigation and input retain their existing APIs.

The bundled extension is now 0.4.6. Its shared tab-creation function selects an
explicit normal window and creates its own normal window when none exists.
Both initial dedicated-page creation and explicit target creation use this
function. This resolves the real "No current window" failure that previously
left the extension connected with no owned page.

Published legacy fixture code remains unchanged. Those fixtures supply their
required host window before accepting the bridge connection. A separate current
extension scenario holds CDP's first page creation until the actual extension
hello names its owned page, then verifies trusted input and one submission.

## Regression evidence

The generated scenarios use an actual Chrome process and an independent CDP actor
on an early startup page. The application request is held by the local HTTP server
while that actor navigates its own page to blank. The application must reach its
owned destination once, type with trusted events, and submit exactly once.

Both default startup and an explicit startup URL are exercised in headless and
windowed Chrome. All four new cases fail against the unchanged startup logic.
After the core change, all seven startup checks passed with zero skips, including
the existing same-page cancellation and wrong-destination refusals. The Python
unit/bridge suites passed 257 checks.
The JavaScript ownership suite passed 12 checks.

Final Chrome 156 live PTY acceptance passed 39 checks with six existing platform
or managed-profile skips. All 19 checks covering the modified startup, windowless
extension, version upgrade and native visibility workflows passed with zero skips.
Chrome 155 compatibility passed all 10 startup/windowless checks with zero skips.
Identity and stealth checks passed 12; cold-start retry and inventory contracts
passed 10. All pre-commit checks passed, and the 63 generated tool wrappers stayed
unchanged.

The scenario source is "tests/integration/scenarios_navigation_startup.json".
The existing remote-view CI jobs already run its generated test module on Windows
and Linux and retain the JSON receipts and rendered neutral-form screenshots.

Local evidence: "scratch/extension-runtime-20261023". The failed CI logs and the
before/after live receipts are retained. This work leaves the real user Chrome
profile recovered by PR #37 untouched.
