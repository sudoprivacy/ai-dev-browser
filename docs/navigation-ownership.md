# Navigation ownership: BR disposition and CLI audit

## Scope and evidence

The incoming Ladder BR ran `0.53.1.dev6+g6cc003336` on Linux Chrome 154.
It lost access to a tool-created page after consent navigation. The report did
not retain Chrome tab replacement/detach events, so its exact cause is unknown.
No Google registration, verification or SMS action was repeated for this fix.

Before these changes, current master `df8dae1` passed five neutral real-extension
journeys: same-page navigation, cross-origin navigation, child window, noopener,
and child opening while its parent closes. Existing same-tab `target_closed`
recovery was already newer than the deployed version. These results do not
prove the original Google failure is reproduced or resolved.

## Behavior

- Ownership comes from deliberate creation, Chrome source/opener events, or
  Chrome's `tabs.onReplaced` mapping. Matching a domain never grants control.
- A proven replacement transfers ownership and records `successorTargetId`.
  An old Python `Tab` reports replacement; it never silently retargets or
  replays input. Removal arriving afterward preserves that diagnosis.
- A debugger cancellation revokes ownership, including during recovery or
  attachment. Revocation survives worker restart and managed-profile discovery.
  With no owned pages, page selection refuses instead of creating an implicit
  new page. An explicit new automation session requires user authorization.
- Worker startup, owned URL updates, creation/source relationships, replacement,
  removal and detach reasons are recorded. History is bounded to 100 events;
  terminal states to 128 entries. Revoked IDs persist for the browser session.
  URLs retain origin/path, omit query/fragment, and reduce non-HTTP URLs to
  their scheme. Unrelated tabs' URLs are not collected in history.

## CLI steering audit

Audit source: `document-ai/.claude/skills/cli-steering-engineering/SKILL.md`.

| Surface | Contract |
| --- | --- |
| Discovery | Existing `cdp_send` core docstring describes `AiDevBrowser.debugState`, its fields, and how to inspect a refusal when no owned page remains. Generated CLI help inherits it. |
| Python / CLI | `OwnershipProtocolError` remains both a protocol exception and a session error. CLI retains the error string and adds the same `details`, semantic code and `retryable: false`. |
| Closed / missing | `target_closed` / `not_found`, exit 4. Missing-page details include redacted owned targets and terminal history. |
| Replaced | `session_changed`, exit 5; a successor is exposed only while still owned and not revoked. Select it explicitly after inspection. |
| Revoked | `auth_failed`, exit 7. Reconnect cannot grant permission. |
| Unowned / unavailable | `unsupported`, exit 6. No domain adoption or automatic transport change. |
| Failure steering | The exception's specific hint overrides generic tool hints. It forbids replaying completed input and explains successor/permission handling. |
| SSOT | Core signatures and generated tool wrappers remain the source for CLI behavior. No additional tool or duplicated argument definition. |

## Regression evidence

The JSON scenarios beside `tests/integration/test_extension_ownership*.py`
generate the tests with the integration-test-generator skill. Helper workflows
use the actual bundled extension, real Chrome, neutral HTTP pages and fresh CLI
processes. Each workflow checks one trusted server submission, reconnects the
same tab, restarts the actual extension worker, rejects an unrelated same-origin
tab, and verifies redacted failure details. Both WebSocket backends run in CI.

The native Linux test clicks Chrome's real **Cancel** permission banner using
X11 input on an isolated display. It requires actual `canceled_by_user` events,
checks refusal on the original Python Tab and a fresh CLI, and verifies that
reconnect and worker restart preserve revocation. CI retains screenshots and
JSON evidence. It does not synthesize Chrome extension events.

Windows Chrome for Testing 155 and Linux Chrome for Testing 154 are exercised
locally. These local Linux runs use Docker Desktop with Xvfb and Openbox; they
are not a test on the reporter's Azure VM. The original Google flow remains
untouched. Chrome's rare `onReplaced` event and attachment/recovery races have
deterministic JavaScript **unit** coverage; a real Chrome tab replacement has
not been reproduced by these fixtures. This is an explicit remaining evidence
limit, not a claim of complete live coverage of every browser event.

### Reproduce

```sh
export AI_DEV_BROWSER_TEST_EXTENSION_CHROME=/path/to/chrome-for-testing
uv run python -m pytest -v tests/integration/test_extension_ownership.py

# Linux, with xvfb, xauth, openbox and xdotool installed:
export AI_DEV_BROWSER_OWNERSHIP_NATIVE=1
for backend in legacy asyncio; do
  xvfb-run -a -s '-screen 0 1280x1000x24' sh -c '
    openbox >/tmp/adb-ownership-openbox.log 2>&1 &
    uv run python -m pytest -v "tests/integration/test_extension_ownership_native.py::test_real_extension_native_consent_revocation[$1]"
  ' _ "$backend"
done
```

Use a fresh isolated test profile and desktop for each native permission test;
reusing one X11 desktop after cancellation did not reliably show Chrome's banner
for the next browser in local testing. Both backends are tested independently.
Neither test needs an API key, external
account or a user's running browser. Skipped native tests do not count as live
verification.

Fixture cleanup has separate deadlines for stopping its owned Chrome and
closing the bridge. `extension-cleanup-evidence.json` retains each phase;
timeouts fail the test and retain Python task/thread stacks. The extension CI
job also has a 25-minute deadline and a three-minute faulthandler dump, so a
stalled teardown cannot silently occupy a runner for hours.
