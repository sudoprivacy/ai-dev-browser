# Extension runtime recovery — 2026-10-23

## Incident and recovery

The Ladder report `BR-ai-dev-browser-extension-runtime-20261023.md` described
Python 0.58.1 with bundle 0.4.4, an unknown running version, a hidden owned page,
and an unsupported window restore. These observations did not establish a
regression in extension 0.4.4.

Read-only inspection confirmed that the real Profile 1 bridge used this repo's
unpacked extension directory. Chrome's extension manager displayed 0.4.3 while
the live worker omitted its version. After synchronizing the published 0.58.3
source, the on-disk bundle was 0.4.5. Neither the disk version nor the manager's
display was substituted for the missing live-worker report.

Recovery used the identified bridge's ordinary Reload button in Chrome's existing
extension manager. No Chrome process was closed or restarted. Native tab identities
confirmed that all 74 existing tabs remained: 47 in one window and 27 in another.
Chrome created one additional dedicated automation tab. The profile identity
remained the same, while the session changed. A read through the old session
binding was refused.

The new explicit connection reported loaded and bundled extension 0.4.5 with a
true match. On its new dedicated tab, a neutral local form passed real-profile
acceptance over live PTY:

- `window_set(state="normal", focus=True)` returned observed `normal`, `visible`,
  `focused=true`, and `input_ready=true`.
- Actual typing used `Input.insertText` and produced a trusted input event.
- The local HTTP server received exactly one submission with a trusted click.
- The final rendered page was inspected, then the dedicated tab returned to blank.

The original login page received no input, navigation or submission from this
work. This does not verify Gmail login, account credentials, verification choices,
or registration QR behavior. The original scene's exact occlusion cause remains
unverified.

## Earlier compatibility guidance

`browser_connect` now returns `extension_warning` whenever the loaded version is
unknown or differs from its bundle. It gives the ordinary update/reload path,
the actual SDK bundle directory, and instructions to reconnect and inspect
session/profile, owned target and real visibility before input. It explicitly
preserves Chrome and existing tabs and warns against replaying submissions.

`connected=true` reports a connection. Unknown compatibility remains unknown;
matching versions alone do not prove page visibility. The warning is null for a
reported version match. Start and reconnect inherit the same result. The low-level
`connect_extension` documentation points workflow startup to this preflight.

The warning and existing three version fields share `extension_version_info` as
their source. CLI wrappers remain generated from core; this adds no tool or
argument, no automatic reload, and no new input fallback. Existing visibility,
ownership and session checks remain in force.

## Regression protection

The generated runtime-upgrade workflow loads the public 0.54.0 wheel's extension
0.4.1, which predates runtime version reporting. It verifies the CLI warning
before input and the unsupported window result. It then updates the fixture's
unpacked files and uses Chrome's normal Developer mode and Reload controls.
Both backends must preserve the Chrome process and all original fixture tabs,
refuse the old session, report the new matching runtime, restore a real window,
and submit the neutral form once with trusted input. The bridge command ledger
must contain no `Input.*` commands before runtime verification.

CDP in this test arranges only its isolated Chrome's extension-management UI and
independently observes tab preservation. Application navigation and input use the
extension transport throughout. The real user profile was recovered through
native accessibility controls for Chrome's ordinary management UI.

The existing public 0.57.7 fixture also verifies that a known version mismatch
returns the warning before the unsupported window operation. Existing native
occlusion tests continue to verify actual hidden-page refusal. CI runs the new
upgrade workflow on all three extension matrix entries and retains its JSON and
rendered PNG.

Local source acceptance passed all 9 checks with zero skips: six real browser
workflows across both WebSocket backends and three import checks. The Python
unit and bridge suites passed 256 checks, including all 69 CLI steering contracts;
the JavaScript ownership suite passed 10. All pre-commit checks passed, including
type and secret checks. Regenerating the 63 tool wrappers changed no wrapper.

Scenario source: `tests/integration/scenarios_extension_runtime.json`.
Local real-profile evidence: `scratch/extension-runtime-20261023`.
Private identity snapshots stay local; public evidence should contain only the
sanitized recovery receipt, neutral-form observations and rendered acceptance.

## Follow-up startup and recording checks

Post-merge CI exposed cold Chrome startup races. Fresh CDP startup now creates
one explicit blank target, waits for its parsed document and a read-only profile
network-context response, then navigates to the requested URL once. A timeout
preserves Chrome and any known session/target for inspection without replay.
The extension's shared tab creation selects an explicit normal window, creating
one when Chrome starts without any windows. Its bundle version is 0.4.6.

The extension fixture closes only browser_start's recorded disposable bootstrap
target. Chrome can attribute that page to the extension's main tab; retaining it
made the original one-owned-tab assertions fail. The main tab must survive the
cleanup with the same identity. Production child ownership rules are unchanged.

A live regression also delays delivery of actual Chrome layout responses by
800ms while input and screencast events continue. The previous recorder completed
one trusted click but produced only three GIF frames, failing the existing pixel
checks. Health sampling now runs independently of the animation timer. Viewport
writes remain in one task; target failures, RPC deadlines, final live checks and
the 550ms click feedback duration retain their existing contracts. The generated
regression runs on both extension backends in all three real-extension CI jobs.

Acceptance with explicit shell proxy settings exposed a separate local-control
gap: bridge status/shutdown and the recorder did not share CDP's existing direct
loopback WebSocket rule. They now reuse the same version-aware helper. Remote
endpoints retain their existing proxy behavior; websockets 13.1 receives no
unsupported argument. A generated real-extension journey verifies its rejecting
outbound proxy, connects through the actual CLI, records trusted click/typing
and checks the saved GIF's expanding ring without sending local control to it.
