# Extension page readiness and explicit recovery — 2026-10-29

## Verified failure

The unchanged PyPI 0.58.12 package, bundled extension 0.4.6 and real Chrome for
Testing 154 reproduced `connected=true`, `tabs=[]`, `tab_count=0` after closing
the dedicated page. An unrelated fixture tab remained open. The regression
failed on that successful exit code, before any navigation was attempted.

A live bridge did not establish that its dedicated page was usable. Bound
connection checks also replaced the extension's authoritative revoked state
with a generic `target_closed` error. The original reason for the reporter's
historical revocation remains unknown.

## Connection and recovery contract

`browser_connect --transport extension` now requires its dedicated page to
exist. It reports `bridge_connected` separately from `page_available`. Missing
pages return `connected=false`; revoked pages retain `auth_failed`, ownership
details, a non-retryable refusal and concrete human recovery instructions.
`browser_reconnect` and bound page tools use the same ownership check.

Terminal states retain their event time in Unix milliseconds. Legacy states
use a matching retained history event when available, otherwise null. Closing
a revoked main page preserves its revocation and main-page identity across
worker restarts. Background reconnect, launch-marker adoption and raw target
creation cannot restore that consent.

With extension 0.4.7, clicking AI Dev Browser in Chrome's toolbar or Extensions
menu explicitly authorizes a fresh visible blank page when the main page is
missing or revoked. The default native shortcut is Ctrl+Shift+Y, or
Command+Shift+Y on macOS; Chrome's shortcut settings can change it. This uses
the existing Chrome action and the existing tab/window activation primitive.

The fresh authorization rotates `session_id`, retains `profile_id`, leaves
previous tabs open and keeps revoked target IDs revoked. Existing bound
drivers are fenced by the bridge's existing session identity checks. Clicking
the action in a healthy session shows the same owned page without rotating
identity or creating another page. No protocol reauthorization tool was added.

## Local acceptance and CI protection

- Windows Chrome for Testing 156: real CLI connect, close dedicated page,
  reconnect and navigation agree on `target_closed`; unrelated tab preserved.
  Both WebSocket backends passed.
- Linux Docker/X11 Chrome for Testing 154: real native Cancel button,
  close revoked main page, restart worker, compare connect/reconnect/navigation/
  new-tab refusals and event time, then invoke Chrome's native action shortcut.
  Both WebSocket backends passed in live terminal runs.
- The fresh page was visibly blank before navigation. It read authenticated
  local HTTP state using the same profile's HttpOnly login cookie. The server
  recorded zero POST requests; an unrelated tab retained its ID, URL and title.
  Old session IDs and already-open old driver connections were rejected.
- Native screenshots were opened and inspected: Cancel before revocation,
  fresh visible blank page, and the authenticated result showing zero approvals
  and zero submissions. These are isolated fixtures, not the user's settings.
- All 313 Python unit tests and 16 extension state/race tests passed.
- Existing lifecycle, installed-profile, OAuth/navigation ownership and CLI
  compatibility workflows: 19 passed together; one Windows headful case had
  its folder picker cancelled during setup and passed on an isolated rerun.
  Both the failed setup receipt and successful rerun were retained.

The scenario JSON files are the workflow source. Tests were regenerated with
the integration-test-generator skill. The extension CI matrix now includes the
missing-page journey. Existing native consent CI executes the expanded recovery
journey on both backends and retains screenshots and receipts. CLI JSON is
retained even when an assertion fails.

Local receipts, including failed setup attempts and the official-package
baseline, are under `scratch/stale-target/`. Native accepted results are in
`linux-acceptance/native-accepted-{legacy,asyncio}`.

The first Windows extension CI passed all 45 primary workflows, then an old
extension fixture timed out obtaining Chrome's CDP identity before connecting.
The same old-extension journey passed locally on both backends. Startup results
are now recorded before the fixture's first assertion, and CI retains Chrome
logs, resource snapshots and cleanup receipts for previous/unknown extensions.
The startup failure's cause is unconfirmed; deadlines, assertions and retry
counts were left unchanged. The affected old/current live journeys passed
again after this diagnostic change (six checks).

## CLI steering audit

Audited against `document-ai/.claude/skills/cli-steering-engineering/SKILL.md`.
The existing core functions remain the source for names, parameters and help;
the generated tool wrappers were unchanged. Actual `browser_connect --help`
exposes bridge/page readiness and visibility before its argument block.
Recovery is delivered in the typed ownership error's runtime hint, with the
same state/details through core, fresh CLI processes and reconnect.

No new LLM-facing recovery command or transport choice was introduced. The
agent receives the concrete Chrome action and subsequent connect command at
the failure point. Stored `canceled_by_user` is explicitly described as history,
not evidence that the human cancelled the current request. All 116 existing
CLI help, parameter and error-envelope contract checks passed.

The actual GitHub organization settings were not accessed during acceptance.
