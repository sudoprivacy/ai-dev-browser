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
The initial adapter uses viewport JPEG snapshots. Interactive streaming,
drag/clipboard, frame epochs and session-wide AI/human arbitration require
additional integration; this extraction does not claim those capabilities.

## Full window view

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
