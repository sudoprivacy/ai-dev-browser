# Shared remote browser views

`ai-dev-browser[remote]` provides view adapters for an **existing** browser.
Applications retain their authentication, browser/target selection, billing,
invitation and website policies. The optional `aiohttp` dependency is not needed
for ordinary browser automation or the X11 adapter.

## Page view

```python
from ai_dev_browser.remote.cdp import CDP
from ai_dev_browser.remote.page import PageView

# The host resolves and authorizes this page's socket before connecting.
page = CDP(await http.ws_connect(authorized_page_websocket))
view = PageView()
pixels = await view.capture(page)
await view.input(page, {"kind": "click", "x": 120, "y": 44}, width=480, height=850)
await page.close()  # Disconnect the transport; preserve Chrome and its profile.
```

The host must serialize screenshot/input operations, validate the selected
target, authenticate each controller and enforce control ownership. The adapter
does not launch browsers, select tabs, retry input, authenticate users or grant a
control lease. A new transport can reconnect to the same live browser without
replaying a submission. Native JavaScript dialogs retain the last pixels and
accept explicit dialog input; the host passes the current dialog state.

Input supports viewport clicks, bounded wheel movement, Unicode text insertion,
navigation keys and explicit dialog responses. A click first moves the cursor,
then presses/releases once: real headful Chrome can retain a previous hit-test
location across navigation without that movement. This is verified by the live
headful reload workflow.

`remote/page_view.js` exports `PageSurface`, an ES module for scaled image
display, pointer/keyboard forwarding and mobile scroll gestures. Serve the
packaged asset through the application's own endpoint:

```python
from importlib.resources import files
javascript = files("ai_dev_browser.remote").joinpath("page_view.js").read_text()
```

```javascript
import { PageSurface } from '/authorized-host/page-view.js';
const surface = new PageSurface(imageElement, sendAuthorizedInput);
surface.frame({ data: jpegBase64, width: 480, height: 850 });
surface.dispose();
```

The application supplies accessible controls for Unicode/IME text insertion,
dialogs and supported keys. `PageSurface` is a rendering/input adapter, not a
complete tab bar, toolbar, WebSocket authorization protocol or React panel.
Hosts whose worker advertises `capabilities.dragInput` can opt into mouse/pen
selection with `new PageSurface(imageElement, sendAuthorizedInput, {drag: true})`.
When `capabilities.liveDragSurfaces` includes `"page"`, also pass
`{liveDrag: true, viewerId}` using that attached page viewer's ID. The checked
input callback must return the API acknowledgement promise. Page gestures use
the same bounded, sequenced `drag-stream` packets and input barrier as window
gestures. Pixels remain observable while the button is held; closing the viewer
releases the button and fences stale coordinates without returning control to AI.
Headless CDP and managed extension browsers need no X11/VNC service for this.
Older workers without the surface capability keep the bounded `drag` fallback;
the legacy `liveDragInput` flag alone does not advertise page streaming.
Touch gestures scroll by default. A host can offer an explicit "Select text or
drag" gesture mode with `{drag: true, touchDrag: true}`. A cancelled touch sends
no partial drag; switching away from a surface must dispose it before accepting
another gesture. The existing host lease and epoch checks still apply. This is
an input mode, not an ownership transfer or permission to resume AI. The real
Chrome touch-emulation journey scrolls out and back in the default mode, then
selects the exact phrase in drag mode through a separate scaled viewer. It also
checks cancellation before a completed gesture. Physical iOS/Android acceptance
remains a separate device requirement.

A drag carries at most 64 viewport points in
one bounded `input` operation; it is sent on pointer release, so this is not a
continuous drag stream. The host's existing input barrier drains the gesture
before changing control or targets. The adapter never retries it.

### Live dragging in a streamed window

For a window using independently streamed pixels, a worker advertising
`capabilities.liveDragInput` supports acknowledged motion before pointer release.
Opt in explicitly with `{drag: true, liveDrag: true, viewerId}` on `InputSurface`.
The viewer ID must be the same ID attached to that window. Its send callback
must return a promise that resolves only after the checked input API succeeds
and rejects on failure. Hosts retain their normal input error reporting.
Keep the legacy bounded gesture for JPEG views: their frame capture shares the
input barrier and cannot display intermediate motion during a live press.

The mapper coalesces unsent positions and waits for each acknowledgement. It
sends one `drag-stream` gesture ID with increasing `sequence` values and
`begin`, `move`, `end` or `cancel` phases through the normal window input API.
Each packet includes the attached `viewerId` and current control/target epochs.
The worker binds the entire gesture to that controller, viewer and target,
keeping one input operation locked from the native press through release.
Status reads use its last observed target while pressed; they do not refresh
or select another target between packets. Pixel transport remains read-only.

Stream disconnection, detach, surface changes and cancellation release the native button. An abandoned gesture is
released after five seconds without a packet, with a thirty-second total
gesture limit. These are input cleanup bounds: they never return control to AI
or change the human owner. A failed release puts control in an error state and
advances the epoch to fence queued coordinates. Input is never replayed after a
failed packet. Cancelled and abandoned gestures advance the epoch to reject
queued coordinates. Switching input modes or resizing a surface cancels its gesture.
Mouse and touch-drag modes use the same protocol; default touch scrolling stays
unchanged. Physical phone and consumer application acceptance remain separate.

Workers advertising `selectionRead` accept the human-only input
`{kind: 'input', input: {kind: 'copy-selection'}, controlEpoch, targetEpoch}`.
It uses the existing authenticated input gateway and barrier. Its `selection` result contains
`{text, isAvailable}` from the selected page, including focused text inputs.
Password fields, cross-origin focused frames and selections longer than 8192
UTF-16 code units return unavailable. Reading does not access an OS clipboard.
An application can copy this result to the local clipboard from an explicit
user gesture, with the normal browser permission/error handling. Do not silently
read local clipboard content or resume the agent as a consequence of copying.

`input: {kind: 'paste', text}` inserts up to 8192 characters, including newlines,
tabs and Unicode, into the current target. Other control characters are refused.
The X11 adapter uses its isolated display's clipboard; the page adapter uses
trusted CDP input. Both retain the same lease and reject stale queued input.
Applications provide their own accessible paste/IME control and may wire native
clipboard shortcuts to these operations after checking the capability flags.

The adapter still uses JPEG snapshots. Continuous streaming, native clipboard
permission UX and application-specific review targets require integration.
The control primitive below
supports session-wide arbitration; hosts still wire its epochs into frames,
tool execution and viewer input.

## AI and human control

The agent communicates why human input is needed through its native question,
options or normal conversation. The host's existing authenticated interrupt
and continuation actions perform the actual ownership transition. A native answer is only
communication unless the host explicitly routes it to that authenticated action
and waits for the tool barrier. Do not require separate browser business handoff
buttons or build an additional question UI into the
remote display adapter. Credentials are entered in the same browser by the
human, not sent through agent chat. The public MCP tool catalog and normal CLI
mode help include this guidance; execution barriers remain a host contract.

`remote.control.BrowserControl` serializes operations across every agent and
viewer attached to one browser. Hosts supply authenticated actor identities,
isolate the raw browser endpoint and share one instance across all targets.

```python
from ai_dev_browser.remote.control import BrowserControl, SharedViewer

control = BrowserControl()
await control.run("ai", control.epoch, control.target_epoch, browser_operation)
human_state = await control.take(authenticated_controller_id)
# take() blocks new AI writes immediately and drains the current operation.
await control.run(authenticated_controller_id, control.epoch,
                  control.target_epoch, trusted_human_input)
state, fresh_page = await control.give_back(authenticated_controller_id,
                                          fresh_observation)
```

After a transfer or target change, operations carrying an old epoch are
rejected, including those already queued behind another operation. Arbitrary
JavaScript evaluation must not be marked as an observation. The host permits
only an exact read-only allowlist. An interrupted takeover keeps execution
stopped; a failed or canceled return observation retains human control.
Viewer disconnect never calls `give_back`. A different viewer does not replace
the controller without an explicit authorized transfer.

Worker status remains available while a browser starts, stops or is rebound.
During that transition it reports `pausing`, retains the human control lease,
and disables page/window input until the operation finishes. Status never
queries a retiring browser driver or reconnects it automatically.

The operation lock covers complete atomic input sequences, including releasing
pressed input. A host with unrestricted agent shell access must also pause and
drain those agents; the Python operation gate alone cannot stop a shell from
calling Chrome directly. Real agent/runtime acceptance remains a consumer test.

`SharedViewer(create_view, close_view)` shares one lazy adapter across viewer
identities. `attach(id)` creates it only on first use; `detach(id)` closes it
after the last viewer leaves. Its callbacks own display resources, not Chrome
or profile storage. Headless sessions run no X display/VNC services. A headful
session can acquire `VncView` only when its window viewer is requested. A frame
producer can follow the same lifetime so idle automation performs no encoding.

## A shared browser session

### Optional existing personal Chrome attachment

Local application hosts can opt into explicit attachment with the worker's
`--existing-extension-root <host-owned-directory>`. All conversations in that
host must use the same directory so an OS file lease prevents two workers from
claiming the same extension profile. Cloud workers omit this setting; neither
an agent nor an untrusted request can enable it or supply a profile path.

The authenticated host first invokes `inspect-existing-extension`. It returns
the currently connected extension's opaque `sessionId` and `profileId`, plus
normal installation guidance. Show this identity to the user and request
explicit selection. Then invoke `connect-existing-extension` with those exact
two fields after the application's agent execution barrier has acknowledged
human control. A changed Chrome/profile is rejected without choosing another
browser or launching a replacement. The ordinary extension continues to expose
only its dedicated automation tab and descendants.

The connected session uses the same control, page view and browser tools as
managed Chrome. Personal Chrome's launch mode may be unknown and is reported as
`isHeadless: null`; it is never invented or changed. `lifecycle` and
`fileTransfer` are false: attachment does not reconfigure the user's downloads,
restart Chrome or close it. To finish, the human host invokes
`disconnect-existing-extension` with current control/target epochs. It releases
the connection and shared profile lease, leaving Chrome, page state and login
cookies intact. Disconnect does not silently return control to AI. Application
shutdown also releases only the attached connection. A restored worker requires
explicit reconnection to the same personal identity or explicit disconnection.
If a worker crashed under an AI lease, the restored authenticated host can
explicitly disconnect the stopped reference using current epochs after its
agent barrier. This acquires human control without launching or switching
Chrome. Stale epochs and a different retained human controller are rejected.

`test_existing_worker_live.py` exercises actual Chrome and both WebSocket
backends: explicit profile verification, two-conversation ownership, rejected
AI attachment/writes, trusted Unicode input, fresh observation, original cookie,
single submission, a real worker crash, recovery and disconnection while
personal Chrome remains running.

`remote.session.BrowserSession` binds the selected target, control lease and
lazy viewers to an already authorized `BrowserClient`. The host supplies trusted
viewer/controller identities. `take()` drains in-flight writes; `give_back()`
requires a current screenshot and accessibility tree. Agent CDP commands,
including JavaScript evaluation, pass through the same lease. Switching a tab
invalidates queued inputs and frames through the target epoch. Disconnecting a
viewer retains both the browser and human ownership.

The host still owns authorization, durable state, tenant isolation and endpoint
access. Keep raw CDP/extension endpoints outside the agent's execution namespace;
calling this session API alone cannot constrain a separate unrestricted shell.
The extension bridge refuses browser-page WebSocket origins so a page cannot
open the loopback driver and bypass the host boundary.

For a host-owned initially empty cloud profile,
`remote.provision.prepare_managed_extension_profile()` verifies installation
through Chrome's machine policy and a signed extension update server, then
stops the bootstrap browser before normal extension launch. It checks the exact
extension ID, preserves background networking for policy installation and
refuses arbitrary existing profiles. The host provides the policy/update server
and exclusive profile ownership; the SDK does not modify extension preferences
or install unpacked code into a user's browser.

An extension launch keeps its owned loopback handshake page until the caller
navigates. The handshake does not schedule an additional blank-page navigation:
that can invalidate Chrome's debugger target after readiness was announced.
An explicit launch URL still uses the normal caller-requested navigation.

### Managed Chrome image

`deploy/managed-chrome/Dockerfile` is the shared Linux runtime for consuming
hosts. It installs branded stable Chrome and packages the bridge using Chrome's
supported signing/policy installation. The caller supplies a stable signing key
as a BuildKit secret; it is never copied into an image layer. Reuse that key for
updates to persistent profiles.

```sh
docker build -f deploy/managed-chrome/Dockerfile \
  --secret id=extension_key,src=/private/extension-signing.pem \
  --build-arg SOURCE_REVISION=<validated-git-commit> -t managed-chrome .
```

The host serves `/opt/browser/extension/update.xml` and `bridge.crx` on container
loopback port 8080 during installation and updates. The image launches no HTTP,
X11 or VNC service by default; hosts provide their authorized session API and
start display resources when required. Chrome runs as UID 10001. Persist its
host-owned profile separately from the image, enforce one runtime owner, and
pin production images by digest after validating their recorded Chrome version.
Docker hosts must use `--init` or another child-reaping supervisor so exited
Chrome descendants do not accumulate against the runtime's process limit.
The `Managed branded Chrome` CI job uses an isolated fixture signing key and
real installed headless extension to exercise the same shared-session workflow
as CDP, including trusted input, handoff and stale-target rejection.

## Full window view

For managed headful Chrome, `XDisplay()` starts an isolated Xvfb display and
Openbox window manager. `await display.start()` returns its display name;
`await display.close()` stops only those owned processes. Install `openbox`
and `x11-utils` alongside Xvfb. Create it only for a headful browser. A window
manager provides native keyboard focus, tab shortcuts and window activation;
an Xvfb framebuffer alone does not provide those desktop behaviors.

For an authenticated host that already transports page frames and typed input,
`ai_dev_browser.remote.window.WindowView(display=isolated_display)` captures the
same isolated X11 Chrome window as JPEG frames and accepts native mouse, text
and keyboard input. Install `xdotool`, `xclip` and Pillow. Text travels through stdin;
input is bounded and never retried. Wrap every call in the host's control lease.
Unicode text uses a native paste on this isolated display, avoiding temporary
keyboard mappings that can drop characters under load. Clipboard ownership
lasts until the next text insertion or `await view.close()`. Close each window
view before its display. The user's local desktop clipboard is never accessed.
This adapter starts no display, browser or listening service. The host can
reuse `PageSurface` for both page and window pixels.

After native input, call `BrowserSession.follow_foreground(controller, epoch,
target_epoch)` under the authenticated human identity. A tab switch invalidates
old coordinates and updates the target used by AI's fresh observation. The
machine-managed image explicitly sets `ManagedBrowserProfile` to share every
tab in its isolated profile. Ordinary installed extensions continue to expose
only dedicated automation tabs. Profile preparation enforces `minimum_version`
before the host exposes normal agent control. An older installation is updated
through Chrome's native Update action, then verified against its installed
version and bridge handshake while preserving the same persistent profile.

This uses Chrome's [managed storage schema](https://developer.chrome.com/docs/extensions/reference/manifest/storage)
and the [extension manager's native update API](https://chromium.googlesource.com/chromium/src/%2B/4c400b5eade7/chrome/browser/resources/extensions/service.ts).
Version enforcement belongs to the host's preparation step. In the actual
Chrome 155 migration fixture, setting Chrome's minimum-version policy disabled
the older extension and crashed bootstrap; the host check preserves the version
requirement while allowing Chrome to perform the signed update.

`WindowView.input` supports native `AddressBar`, `NewTab`, `NextTab`,
`PreviousTab` and `CloseTab` keys alongside the page input keys. Hosts should
offer toolbar controls for these actions because a web browser reserves some
keyboard shortcuts for its own local window.

Install system `xvfb`, `x11vnc`, `novnc`, `websockify` and `xauth`. Launch Chrome
on a dedicated X display, then use:

```python
from ai_dev_browser.remote.vnc import VncView

with VncView(display=isolated_display, password_file=private_password_path,
             vnc_port=owned_vnc_port, web_port=owned_http_port):
    run_operator_assisted_workflow_on_the_existing_browser()
```

The adapter binds only loopback, verifies startup and cleans up only the
processes it spawned. The caller owns the private password file and isolated
display. Use an authenticated tunnel or application gateway to expose the
viewer. Closing a view preserves the browser/profile; restarting or closing a
browser is a separate lifecycle operation. VNC renders the entire supplied
display, so a display must not be shared across users.

## Integration ownership

### Shared application worker

`ai_dev_browser.remote.worker.Worker` hosts the same session, persistent profile,
control journal, HTTP MCP, page viewer and file transfer for local and cloud
applications. The application authenticates users and supplies an opaque
`orgId`/`userId`/`sessionId` binding. It owns deployment, account access and the
agent execution barrier. Host and AI credentials must be distinct. The AI
credential cannot take or return human control.

Use `display_mode="native"` for Desktop. Chrome runs on the user's desktop and
the shared panel can render its page surface. Native window controls remain in
Chrome; the worker reports `windowView=false`. Use `display_mode="x11"` for an
isolated Linux display and the existing remote window surface. Headless browsing
starts no display process. Every browser launch still requires an explicit
`isHeadless` choice; display mode does not decide it.

The host can configure a signed managed extension directory and Chrome launch
arguments. The worker does not change Chrome policy or disable its sandbox by
default. Cloud containers supply their own deployment policy.

The standalone worker binds loopback by default:

```sh
python -m ai_dev_browser.remote.worker --profile-root /owned/profile \
  --display native --host 127.0.0.1 --port 8080
```

Supply `AI_DEV_BROWSER_WORKER_HOST_TOKEN` and
`AI_DEV_BROWSER_WORKER_AI_TOKEN` through the environment. The worker removes
them before Chrome starts. Remote exposure requires the application's
authenticated gateway. `X-ADB-Browser-Context` scopes file transport and
`X-ADB-Browser-Session` scopes MCP calls; existing Moss headers remain compatible.

#### Agent commands in embedded pages

`browser_action(kind="command", method=..., paramsJson=..., frame=...)` can
address a cross-origin iframe inside the selected tab. Use the iframe's exact
`frameId` from `DOM.describeNode`, or a URL substring that identifies one
descendant. Omit `frame` for the top page. Nested frames are supported;
extension child sessions require Chrome 125 or newer.

The worker reuses the SDK's selected-tab frame resolver. It resolves and sends
on the same connection because native CDP child session IDs belong to that
connection. Callers supply a frame selector, never a raw debugger session ID.
Browser/Target methods remain outside the command allowlist. Missing, foreign,
ambiguous or malformed selectors return `invalid_browser_frame`; protocol
errors keep their generic public code and private host diagnostics.

Bridge and worker CDP sockets use the same bounded message size as the native
SDK transport. DOM events can include a review iframe's entire `srcdoc`
attribute, even when a query returns only a node ID. These events and large
replies must preserve the connection rather than disconnecting other viewers
or agents. The live workflow exercises a 5 MiB DOM attribute event and reply.

Frame lookup and execution stay within the existing control barrier. Main and
child agents share the same human lease and control/target epochs. Switching
tabs invalidates queued operations; human control rejects frame reads and
writes through this command path. An uncertain input is never replayed.
The host uses its normal question, interrupt and continuation UX; these APIs
do not require additional business handoff buttons.

Real HTTP MCP acceptance covers native CDP and signed managed extension Chrome,
nested reads, trusted Chinese input, two tabs with identical child URLs,
invalid selectors, private protocol failures, stale target epochs and human
control blocking a frame write. Host/model and public-page acceptance remain
separate requirements.

Real HTTP acceptance on Windows covers native headless and headful Chrome, two
viewers of one target, trusted Unicode input, blocked AI writes during takeover,
fresh observation after return, and one trusted submission with the original
cookie. The same journey runs in Linux and Windows CI. Host/LLM acceptance is
still required when an application adopts this worker.

Ladder retains merchant/account checks, selected-plan validation, allowed pages,
invitation revocation, payment retry decisions, OAuth state and proxy identity.
Its private exception adapter maps generic transport errors to existing public
business reasons. SudoWork will share its React BrowserPanel across Desktop and
WebUI while using these adapters for the same adb session.

The host must verify a painted target and a successful initial snapshot before
starting the view stream. DOM load completion alone does not guarantee a
headful compositor frame. Managed headful browsers need an explicit background
rendering policy: an occluded window can stop painting. The live fixtures keep
their owned Chrome painting without changing user Chrome defaults. An existing
user browser needs an accurate capability/error report, rather than an implicit
restart or repeated focus stealing. See Chromium's
[window occlusion documentation](https://chromium.googlesource.com/chromium/src/+/master/docs/windows_native_window_occlusion_tracking.md).

When embedding browser launch in a long-running Python host, use the existing
`browser_start(silent_stderr=True)` option or actively drain Chrome's output.
Its default diagnostic pipe can fill with GPU/Crashpad output and stall the
browser. The two-browser live fixtures use that option while retaining all
pixel, trusted-input and single-submission assertions.

## Real validation

### Uploads and downloads in the shared session

`remote.files.BrowserFiles` stores uploads and completed downloads in an
isolated host directory. Clients receive opaque IDs, filenames, sizes and
SHA-256 values. The host authenticates access, enforces account quotas and
serializes file operations with its profile lease and browser control gate.
File IDs from another store cannot resolve to a local path. Partial downloads,
symbolic links and changed file contents are rejected.

For an idle host-owned profile, `files.configure_managed_profile(profile)`
sets its download directory and disables the save-location prompt. This leaves
extension settings intact and refuses a running profile. Prepare a signed
managed extension profile first, then configure downloads before the final
Chrome launch. Existing user Chrome keeps its own profile settings.

Extension uploads also require Chrome's local file access setting. For an idle
host-owned signed profile, explicitly call
`configure_managed_extension_file_access(..., enabled=True)`; this uses Chrome's
settings API and verifies its active state. A remote host must expose uploads
through approved file IDs and restrict agent commands that accept arbitrary
local paths or file URLs. Keep host credentials outside the browser's readable
files. The extension debugger's file access check is documented in
[Chromium's debugger implementation](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/chrome/browser/extensions/api/debugger/debugger_api.cc).

Pass `files=files` to `BrowserSession` to intercept native file pickers. State
and observations expose a `fileChooser` with an opaque request ID and single/
multiple mode. Stage an authenticated upload with `files.receive(name, bytes)`,
then send `upload-files` with `chooserId` and `fileIds` through the session's
normal actor/epoch gate. Selection applies to that browser target exactly once;
navigation, target changes and consumed chooser IDs invalidate old requests.
The host keeps the file paths private. The default session remains unchanged
when no file store is supplied.

`files.collect_downloads()` lists completed stable files, and `files.path(id)`
verifies their current contents before the host streams bytes to the authorized
user. Application UI, account checks and network transfer stay in the consuming
host. The actual Chrome workflow in `test_browser_files_live.py` verifies
trusted file selection, cookie persistence, exact upload/download contents,
foreign-file refusal and rejection of a repeated chooser operation.

The `Remote browser view` CI job runs Chrome for Testing on Linux and Windows.
It exercises a separate real viewer and target browser: scaled pointer input,
Unicode text, a trusted server-confirmed submission, reconnection to the same
tab/profile, and no replay. The actual extension is tested on both WebSocket
server implementations. Linux also runs real X11/x11vnc/websockify/noVNC,
checks decoded pixels, submits via the viewer and verifies owned cleanup.

```sh
python -m pip install '.[dev,remote]'
python -m pytest -v tests/integration/test_remote_view.py
# Linux, with system viewer dependencies and an isolated X display:
xvfb-run -a -s '-screen 0 1280x1000x24' python -m pytest -v \
  tests/integration/test_remote_view.py tests/integration/test_remote_vnc.py
```

Set `AI_DEV_BROWSER_TEST_EXTENSION_CHROME` to a Chrome for Testing or Chromium
binary to run the actual extension cases. Those cases are skipped locally when
no supported binary is supplied; CI supplies one explicitly. They never install
an extension into the user's real profile.

The managed Chrome CI job also runs `test_remote_window_live.py` with CDP and
the signed extension. It opens a native Chrome tab, follows it, types Unicode
through X11, rejects an AI write during human control, returns a fresh view of
that same tab and verifies one trusted submission with its original cookie.

Native X11 dragging paces the press and bounded motion sequence so Chrome can
deliver multiple movement events to canvas editors. A single coalesced movement
may only cross an editor's drag threshold and leave its first gesture unmoved.
The real canvas regression checks two consecutive gestures, trusted events and
exact pan displacement with both CDP and the signed extension. The gesture stays
inside the existing control lease; its input limits and deadlines are unchanged.

## Host-authorized page launch

The host-only `/invoke` API accepts `kind: "open-authorized-page"` with the
current control/target epochs, an exact `url` and a `cookie` containing `name`,
`value`, `url`, `path`, `httpOnly: true`, `sameSite: "Strict"` and `expires`.
The cookie must be short-lived, scoped below the origin root, and installed
before the first navigation. HTTPS is required except for loopback HTTP. This
operation is unavailable through the AI credential or public agent tools and
is supported by owned CDP browsers and owned managed extension browsers.
Personal Chrome attachments remain outside this capability. Discover support
through `capabilities.authorizedPageLaunch`.

Take the human lease through the existing engine acknowledgement barrier first.
A first host browser start now also takes that barrier before launching Chrome.
The launch opens a new target without overwriting the user's previous tab,
requires an HTML document at the exact requested URL, and returns ordinary
browser state without echoing credentials. On failure it removes the new
cookie and target and restores the previous target when available. It does not
retry navigation. The consuming host must revoke an unsuccessful application
session and verify the intended content; a completed request alone proves
neither application authentication nor successful rendering.

The host may use the read-only `kind: "observe"` operation to inspect the current
target through the existing observation path. Observation does not transfer
input control. Host credentials, session cookies and privileged actions must
never be included in a renderer reply, URL, model context or agent tool schema.
Real-worker tests cover cookie-before-navigation, an unreadable HttpOnly cookie,
reload, foreign/stale leases, AI refusal and compensation after a JSON error page
on both supported transports. The personal-profile journey also rejects this
operation without creating a target or changing its selected tab or epochs.

## Authenticated full-window streaming

The worker can expose a read-only RFB stream of its existing isolated X display.
This is an optional transport for a headful browser, alongside the existing
JPEG/native-input API. It neither launches another Chrome nor takes control.
Headless tasks start no X11 or VNC service. Native Desktop displays report this
capability as unavailable. Linux requires `x11vnc`, `websockify` and the noVNC
system assets; the shared managed Chrome image includes them.

The application host performs these steps through its authenticated gateway:

1. Attach a unique viewer with `surface: "window"` through `/invoke`.
2. Submit `kind: "window-stream"`, that viewer ID and the current control/target
   epochs through the same host API. The reply contains
   `stream: {protocol: "rfb", isViewOnly: true, password: "..."}`. The ephemeral
   protocol password must stay out of URLs, logs and persistent storage.
3. Open the worker's `/window-stream` WebSocket with the host bearer credential
   and `X-ADB-Browser-Context`: URI-encoded JSON containing `binding`,
   `controller`, `viewerId`, `controlEpoch` and `targetEpoch`. Proxy it to the
   already authenticated user and connect a bundled noVNC client. Raw worker
   addresses, privileged headers and VNC listeners stay private.
4. Send human operations through the existing authenticated `input` action with
   `surface: "window"`, under the normal human lease and current epochs.

The host must verify current account/session access before accepting and while
forwarding an established stream, including quiet viewers. The SDK's internal
endpoint authenticates the host; it cannot verify the host's end-user identity.
An AI credential cannot open it. Viewing cannot bind an unclaimed profile or
change the task, browser target or input lease. A second connection using the
same viewer ID is rejected; separate viewers have separate IDs.

Read-only mode is enforced by `x11vnc -viewonly -nosel`, including keyboard,
pointer and clipboard messages from a client that disables its own `viewOnly`
setting. The noVNC client is a display transport; it does not bypass input
ordering, the main/child agent barrier or the existing interrupt workflow.
The worker initializes native input geometry from its host-owned display, so
streaming does not need a redundant JPEG capture before the first input.

A changed binding or epoch, detached viewer, browser lifecycle transition or
lost upstream closes the connection. Input is never replayed. Reconnect reads
the current session and obtains new stream credentials. The last disconnected
stream closes its owned VNC processes; an unused credentials reservation expires
with the existing viewer heartbeat. Chrome, cookies and a human lease survive
view disconnection. Browser shutdown also closes its streams before releasing
the display.

`InputSurface` from `remote/page_view.js` maps the same bounded pointer, touch,
drag and keyboard gestures for an image or a streamed canvas. A streaming host
binds it to the actual noVNC canvas and calls `resize(width, height)` with the
decoded framebuffer dimensions. `PageSurface` extends it with JPEG painting.
Both send through the host's checked input callback; noVNC stays view-only.

`test_worker_window_stream_live.py` exercises actual Chrome, X11, x11vnc,
websockify, noVNC pixels and both CDP/signed extension transports. It verifies
host authentication, rejected raw input, checked native submission, stale
connection closure, reconnect and browser/profile/lease preservation. It runs
in Linux viewer CI and the managed Chrome job. This SDK test does not establish
a consumer's public authentication, graph performance or phone acceptance.
