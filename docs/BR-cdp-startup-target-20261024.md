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
the standard no-startup-window switch. Startup creates and prepares a blank owned
page, then issues the requested URL once through its established page connection.
Creation, initial navigation and document readiness share the existing budget.

The first PR #38 Windows run still caught one bootstrap navigation being aborted.
A held-response probe showed that the target can exist while its temporary empty
document reports readyState=complete. Startup now waits read-only for the initial
document's navigation entry and DOMContentLoaded timestamp within the same budget.
When that budget expires after target creation, the failure includes the persisted
session and exact owned target; reconnect retains both and sends no navigation.

If the creation reply is lost, startup retains the Chrome process and its ownership
record, returns a transient failure, and directs the caller to reconnect and
inspect current pages. It issues no second creation or navigation.

Later CI traces caught explicit startup URLs being cancelled before the HTTP
server received any request, while Chrome initialized its network context.
Creating the application URL before attaching the page connection left that
initialization interleaved with navigation. Preparing the blank page first keeps
page setup before the application request. Readiness also checks that a navigation
with a new loader has left the previous blank document. No request is replayed.
The startup fixture retains native Chrome navigation traces and network logs;
it observes target inventory without opening an extra page debugger session.

A later Windows run passed all six new form journeys but still aborted an older
bootstrap navigation. Initial document readiness alone did not establish that the
profile's network context had responded. Startup now waits for an origin-scoped,
read-only CookieManager RPC in parallel with blank-document readiness. The reply
is discarded. This sends no HTTP request and changes no cookies, so it cannot
replay the user's URL or depend on external network/proxy access. The short
document-timeout fixture loads a separate local readiness document before opening
the launch gate. A CookieManager request on the fixture's cold early target itself
timed out on Windows Chrome 156.0.8078.73, before the scenario began. The readiness
response and parsed DOM now establish that the actual network path works, within
the original ten-second actor preparation budget. That budget belongs to the
async preparation; its cleanup releases the launch gate even on cancellation.
The held application URL is still requested exactly once, and its original
three-second deadline and outcome assertions remain unchanged. Production startup
continues to use the read-only CookieManager probe; it sends no readiness request.

The owned Windows visual fixture also uses the existing integration suite's
`--disable-backgrounding-occluded-windows` flag. Local runs exposed a separate
intermittent failure: document and trusted submission were ready, but no first
paint was recorded and screenshot capture timed out. The fixture must keep
painting beside the user's foreground apps. Production launch flags and the
separate native occlusion tests remain unchanged; screenshot assertions and
command deadlines are retained. Raw failed receipts are kept separately from
the later passing run, rather than treating repetition as evidence of a fix.

Chromium routes this command through the selected target's storage-partition
CookieManager and answers after its callbacks; see the
[Chrome 156 implementation](https://chromium.googlesource.com/chromium/src/+/refs/tags/156.0.8078.47/content/browser/devtools/protocol/network_handler.cc#2366).

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

The added held-initial-document regression failed on the previous commit in both
headless and windowed Chrome: startup incorrectly reported connected before the
HTTP response was released. After the readiness change, both scenarios confirm
the timeout, unchanged process/session/target, one initial GET and one trusted
submission after reconnect. The nine startup checks and eight lifecycle/retry
contracts passed together (17 passed, zero skips).
