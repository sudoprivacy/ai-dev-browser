# BR: extension connect reports success with a stale revoked automation tab

## Impact

An agent cannot start an authorized read-only workflow in the user's existing
Chrome profile. `browser_connect` reports success, but exposes no targets and
retains an unusable automation target. Navigation, discovery, reconnect and
creating a new automation tab cannot proceed. The user sees no new tab.

Observed on Windows 11, Chrome 155, CLI 0.58.7 (reported commit `67014e5`),
loaded and bundled extension 0.4.6. The versions match; `extension_warning`
is null. The user explicitly authorized extension-mode access to their
current profile and says they did not cancel this attempt.

## Actual sequence

From the local ai-dev-browser checkout:

```powershell
python -m ai_dev_browser.tools.browser_connect --transport extension --timeout 20
```

Returns the same existing session on repeated observation:

```json
{
  "session_id": "extension-e69eb01d-db71-4524-b774-1e9c90ecb795",
  "connected": true,
  "automation_target_id": "79220730",
  "targets": [],
  "tabs": [],
  "tab_count": 0,
  "automation_tab_recreated": false,
  "extension_warning": null
}
```

1. `page_goto --session-id <id> --url
   https://github.com/organizations/sudoprivacy/settings/actions` returns
   `target_closed`: `Original automation target is closed; inspect current state`.
2. `page_discover --session-id <id>` returns the same error.
3. `browser_reconnect --session-id <id>` returns `connected: false`,
   `reconnected: false`, `target_closed`.
4. A fresh `browser_connect --transport extension --timeout 20` again returns
   `connected: true`, zero targets and the same original target.
5. Explicit `tab_new --transport extension --url <same settings URL>` returns
   `auth_failed`: `Target is not an owned automation tab (revoked)`;
   details identify target `79220730`, state `revoked`, reason
   `canceled_by_user`. No page was created.

The ownership history contains old worker-start and tab activity spanning
multiple days. The error label does not establish that the user cancelled the
current request, nor which historical event caused revocation.

## Source findings and hypothesis

- `core/browser.py`, extension branch of `browser_connect`: enumerates
  `browser.tabs`, reads `status.automation_target_id`, writes the session record
  and returns `connected: true`. A live bridge can therefore be reported as a
  successful connection even when its original automation page is absent.
- `extension/background.js`, `ensureDedicatedTabSelected`: checks
  `revokedTabs.has(mainTabId)` before checking whether that tab still exists.
  A stale revoked main tab prevents reaching the blank-tab creation path.
- `core/connection.py`: correctly refuses to replace revoked consent with an
  implicit new tab. This consent boundary should be preserved.

These code paths explain the observed contradiction. The original cause and
timing of the stored revocation have not been established.

## Expected behavior

1. Distinguish a connected extension bridge from a usable automation page.
   Return the actual ownership state and an actionable error when the page is
   absent/revoked; do not advertise a usable session solely from bridge liveness.
2. Offer a supported, explicit user reauthorization/new-session flow in the
   same profile. Explain the concrete browser action needed. Do not silently
   restore revoked consent, attach to unrelated user tabs, or change transport.
3. Treat `canceled_by_user` as a stored reason, with event time when available;
   do not imply a cancellation occurred during the current connection attempt.

## Suggested live regression

Use real installed-extension Chrome: establish a session, exercise debugger
consent revocation, close its main tab and restart the service worker. Verify
that connect/reconnect/navigation agree on page readiness; explicit authorized
recovery produces a visible dedicated page and a successful authenticated
read. Preserve unrelated tabs and assert that revocation is never bypassed.

No extension state was edited, consent bypassed, Chrome restarted, or unrelated
tab adopted during this investigation. Organization settings remain unread.
