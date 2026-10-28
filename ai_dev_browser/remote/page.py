"""Page pixels and trusted input, independent of business and user policy."""

import math
import time


class PageDrag:
    """Trusted pointer on one caller-owned page, used by the shared LiveDrag.

    The worker holds the input barrier for the entire gesture. Retain this
    exact connection through release so a tab switch cannot redirect input.
    """

    def __init__(self, page, width, height):
        self.page, self.width, self.height = page, width, height
        self.point = None

    async def press(self, point):
        self.point = point
        await self.page.call("Page.bringToFront", timeout=5)
        await self.page.call(
            "Input.dispatchMouseEvent", {"type": "mouseMoved", **point}, timeout=5
        )
        await self.page.call(
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                **point,
                "button": "left",
                "buttons": 1,
                "clickCount": 1,
            },
            timeout=5,
        )

    async def move(self, point):
        self.point = point
        await self.page.call(
            "Input.dispatchMouseEvent",
            {"type": "mouseMoved", **point, "button": "left", "buttons": 1},
            timeout=5,
        )

    async def release(self):
        if self.point is not None:
            await self.page.call(
                "Input.dispatchMouseEvent",
                {
                    "type": "mouseReleased",
                    **self.point,
                    "button": "left",
                    "buttons": 0,
                    "clickCount": 1,
                },
                timeout=2,
            )
            self.point = None


class PageView:
    """Render and operate an explicitly selected page on a caller-owned CDP.

    The host must authenticate the controller, enforce its control lease and
    authorize the target before each call. This adapter never changes targets,
    connects to another browser, navigates, or automatically replays input.
    It works with a CDP-compatible extension bridge as well as standalone CDP.
    """

    def __init__(self, *, quality=65, max_text=512, max_wheel=600):
        if not 0 <= quality <= 100 or max_text <= 0 or max_wheel <= 0:
            raise ValueError("Invalid view limits")
        self.quality = quality
        self.max_text = max_text
        self.max_wheel = max_wheel
        self.last_frame = ""

    async def capture(self, page, *, dialog=None):
        # Runtime.evaluate and captureScreenshot can block while a native JS
        # dialog is open. Keep its last pixels and expose the dialog separately.
        if not dialog:
            screenshot = await page.call(
                "Page.captureScreenshot",
                {
                    "format": "jpeg",
                    "quality": self.quality,
                    "captureBeyondViewport": False,
                },
            )
            self.last_frame = screenshot["data"]
        return self.last_frame

    async def input(self, page, event, *, width, height, dialog=None):
        """Return whether valid input was sent; reject malformed coordinates.

        Coordinates refer to the rendered viewport's CSS pixels. Resize and
        policy are host decisions. Text uses trusted Input.insertText and
        allows Unicode, including mobile IME output. No input is retried.
        """
        if not isinstance(event, dict):
            return False
        kind = event.get("kind")
        if kind == "dialog" and dialog:
            await page.call(
                "Page.handleJavaScriptDialog",
                {
                    "accept": event.get("accept") is True,
                    "promptText": str(event.get("text", ""))[: self.max_text],
                },
            )
            return True
        if dialog:
            return False
        if kind == "drag":
            points = drag_points(event, width, height)
            if points is None:
                return False
            # One bounded gesture stays inside the host's input barrier. A tab
            # change cannot split a held mouse button across different pages.
            deadline = time.monotonic() + 5

            async def send(params):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Browser drag timed out; input was not replayed")
                await page.call("Input.dispatchMouseEvent", params, timeout=remaining)

            await page.call("Page.bringToFront", timeout=5)
            position = points[0]
            await send({"type": "mouseMoved", **position})
            try:
                await send(
                    {
                        "type": "mousePressed",
                        **position,
                        "button": "left",
                        "buttons": 1,
                        "clickCount": 1,
                    }
                )
                for position in points[1:]:
                    await send(
                        {
                            "type": "mouseMoved",
                            **position,
                            "button": "left",
                            "buttons": 1,
                        }
                    )
            finally:
                await page.call(
                    "Input.dispatchMouseEvent",
                    {
                        "type": "mouseReleased",
                        **position,
                        "button": "left",
                        "buttons": 0,
                        "clickCount": 1,
                    },
                    timeout=2,
                )
            return True
        if kind in ("click", "wheel"):
            try:
                if isinstance(event.get("x"), bool) or isinstance(event.get("y"), bool):
                    return False
                x, y = float(event.get("x", -1)), float(event.get("y", -1))
            except (TypeError, ValueError, OverflowError):
                return False
            if not (
                math.isfinite(x)
                and math.isfinite(y)
                and 0 <= x < width
                and 0 <= y < height
            ):
                return False
            if kind == "wheel":
                try:
                    delta = float(event.get("dy", 0))
                except (TypeError, ValueError, OverflowError):
                    return False
                if not math.isfinite(delta):
                    return False
            await page.call("Page.bringToFront")
            if kind == "click":
                # Real headful Chrome can retain the previous hit-test location
                # after navigation until the cursor moves. Position it before
                # the press/release pair; never retry a click on uncertain state.
                await page.call(
                    "Input.dispatchMouseEvent",
                    {"type": "mouseMoved", "x": x, "y": y, "button": "none"},
                )
                for phase in ("mousePressed", "mouseReleased"):
                    await page.call(
                        "Input.dispatchMouseEvent",
                        {
                            "type": phase,
                            "x": x,
                            "y": y,
                            "button": "left",
                            "buttons": 1 if phase == "mousePressed" else 0,
                            "clickCount": 1,
                        },
                    )
            else:
                await page.call(
                    "Input.dispatchMouseEvent",
                    {
                        "type": "mouseWheel",
                        "x": x,
                        "y": y,
                        "deltaX": 0,
                        "deltaY": max(-self.max_wheel, min(self.max_wheel, delta)),
                    },
                )
            return True
        if kind in ("text", "paste"):
            text = event.get("text", "")
            if (
                isinstance(text, str)
                and 0 < len(text) <= (8192 if kind == "paste" else self.max_text)
                and not any(
                    ord(c) < 32 and (kind != "paste" or c not in "\n\r\t") for c in text
                )
            ):
                await page.call("Input.insertText", {"text": text})
                return True
        elif kind == "key":
            key = event.get("key")
            allowed = {
                "Tab": 9,
                "Enter": 13,
                "Backspace": 8,
                "Delete": 46,
                "Escape": 27,
                "ArrowLeft": 37,
                "ArrowUp": 38,
                "ArrowRight": 39,
                "ArrowDown": 40,
                "Home": 36,
                "End": 35,
            }
            if key == "SelectAll":
                params = {
                    "key": "a",
                    "code": "KeyA",
                    "windowsVirtualKeyCode": 65,
                    "modifiers": 2,
                }
            elif isinstance(key, str) and key in allowed:
                params = {
                    "key": key,
                    "code": key,
                    "windowsVirtualKeyCode": allowed[key],
                    "modifiers": 8 if event.get("shift") else 0,
                }
            else:
                return False
            for phase in ("keyDown", "keyUp"):
                await page.call("Input.dispatchKeyEvent", {"type": phase, **params})
            return True
        return False

    async def selection(self, page):
        """Read bounded selected text from the current page, never the OS clipboard.

        The host must hold its authenticated human lease and target epoch. This
        deliberately does not search another tab or cross-origin iframe.
        """
        return await page.js("""(() => {
            let doc = document;
            for (let depth = 0; depth < 8; depth++) {
                const active = doc.activeElement;
                if (active?.tagName !== 'IFRAME') break;
                try {
                    if (!active.contentDocument) return {text: '', isAvailable: false};
                    doc = active.contentDocument;
                } catch { return {text: '', isAvailable: false}; }
            }
            const active = doc.activeElement;
            let text;
            if (active?.tagName === 'INPUT' && active.type === 'password')
                return {text: '', isAvailable: false};
            if (typeof active?.selectionStart === 'number')
                text = active.value.slice(active.selectionStart, active.selectionEnd);
            else text = doc.getSelection()?.toString() || '';
            if (text.length > 8192) return {text: '', isAvailable: false};
            return {text, isAvailable: true};
        })()""")


def drag_points(event, width, height):
    """Validate the complete path before any native button is pressed."""
    points = event.get("points")
    if not isinstance(points, list) or not 2 <= len(points) <= 64:
        return None
    result = []
    for point in points:
        if not isinstance(point, dict):
            return None
        if any(type(point.get(key)) not in (int, float) for key in ("x", "y")):
            return None
        x, y = point["x"], point["y"]
        if not (
            math.isfinite(x) and math.isfinite(y) and 0 <= x < width and 0 <= y < height
        ):
            return None
        result.append({"x": x, "y": y})
    return result
