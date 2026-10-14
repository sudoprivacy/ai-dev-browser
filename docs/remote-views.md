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
The initial adapter uses viewport JPEG snapshots. Interactive streaming and
drag/clipboard require additional integration. The control primitive below
supports session-wide arbitration; hosts still wire its epochs into frames,
tool execution and viewer input.

## AI and human control

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
