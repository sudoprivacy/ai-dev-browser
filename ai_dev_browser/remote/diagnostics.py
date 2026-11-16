"""One host-authorized DOM/AX/full-page PNG read on the existing page socket.

Nothing here starts a browser, supplies a grant, writes an artifact or replays
an action. Raw diagnostic bytes are host-private; do not add them to replay's
safe metadata or expose this callable as an untrusted CDP endpoint.
"""

import asyncio
import base64
import copy
import io
import json
import math
from collections.abc import Awaitable, Callable
from typing import Any, cast

from PIL import Image

from .control import ControlError, check_effect_authorization
from .frame_facts import page_frames

Assertion = Callable[[], Awaitable[None]]
FrameAssertions = Callable[[str, dict[str, Any]], Awaitable[Assertion]]
MAX_BYTES = 16 * 1024 * 1024
MAX_CSS_PIXELS = 16 * 1024 * 1024
_SOURCE_EVENTS = {
    "Page.frameAttached",
    "Page.frameDetached",
    "Page.frameNavigated",
    "Page.navigatedWithinDocument",
    "Page.frameStartedNavigating",
    "Runtime.executionContextsCleared",
}


def _image_size(data: str, width: int, height: int) -> tuple[int, int]:
    if len(data) > (MAX_BYTES + 2) // 3 * 4:
        raise ControlError("browser_diagnostic_too_large")
    try:
        raw = base64.b64decode(data, validate=True)
        if len(raw) > MAX_BYTES:
            raise ControlError("browser_diagnostic_too_large")
        with Image.open(io.BytesIO(raw)) as image:
            actual = (int(image.width), int(image.height))
            if image.format != "PNG" or actual[0] * actual[1] > 64 * 1024 * 1024:
                raise ValueError
        if not math.isclose(
            actual[0] * height,
            actual[1] * width,
            rel_tol=0.001,
            abs_tol=max(width, height),
        ):
            raise ValueError
        return actual
    except ControlError:
        raise
    except Exception:
        raise ControlError("browser_diagnostic_image_invalid") from None


async def capture_diagnostics(
    session: Any,
    epoch: int,
    target_epoch: int,
    *,
    before_read: Assertion,
    authorize_frame: FrameAssertions,
) -> dict[str, Any]:
    """Require original current read authority and every source projection.

    ``before_read`` covers this held principal/browser/diagnostic purpose.
    ``authorize_frame(target_id, facts)`` must return an async None-or-raise
    assertion for the SAME principal's full DOM/AX/pixels/source/DLP read on
    that original frame. Facts are original checked-replay frame facts, not a
    permission. Child frames also need authority even for full-page pixels.
    Call outside another control.run. Storage and its writer stay with host.
    """
    if not callable(before_read) or not callable(authorize_frame):
        raise ControlError("browser_authorization_required")
    if type(epoch) is not int or type(target_epoch) is not int:
        raise ControlError("stale_browser_operation")
    control, target = session.control, session.target_id

    async def capture() -> dict[str, Any]:
        if session._dialog:
            raise ControlError("browser_dialog_requires_response")
        page = await session._connect_page()
        invalidated = False
        assertions: list[Assertion] = []

        def source_event(method: str, params: dict[str, Any]) -> None:
            nonlocal invalidated
            if method in _SOURCE_EVENTS:
                invalidated = True

        def same() -> None:
            control._authorize("ai", epoch, target_epoch, True)
            if (
                session.control is not control
                or session.target_id != target
                or session._page is not page
                or page.disconnected
                or invalidated
                or session._dialog
            ):
                raise ControlError("browser_diagnostic_context_changed")

        async def grants() -> None:
            same()
            await check_effect_authorization(before_read)
            same()
            for assertion in assertions:
                await check_effect_authorization(assertion)
                same()

        page.add_event_handler(source_event)
        try:
            await grants()
            frames = await page_frames(page)
            await grants()
            if any(
                not isinstance(frame.get("id"), str)
                or not frame["id"]
                or not isinstance(frame.get("loaderId"), str)
                or not frame["loaderId"]
                for frame in frames
            ):
                raise ControlError("browser_diagnostic_frame_invalid")
            for frame in frames:
                try:
                    assertion = await authorize_frame(target, copy.deepcopy(frame))
                except PermissionError:
                    raise ControlError("browser_authorization_denied") from None
                except Exception:
                    raise ControlError("browser_authorization_unavailable") from None
                if not callable(assertion):
                    raise ControlError("invalid_browser_authorization")
                assertions.append(assertion)
                await grants()

            async def current() -> None:
                await grants()
                observed = await page_frames(page)
                await grants()
                if observed != frames:
                    raise ControlError("browser_diagnostic_context_changed")

            async def read(method: str, params: dict[str, Any] | None = None) -> Any:
                await current()
                value = await page.call(method, params)
                await current()
                return value

            document = await read("DOM.getDocument", {"depth": -1, "pierce": True})
            accessibility = await read("Accessibility.getFullAXTree")
            if not isinstance(document.get("root"), dict) or not isinstance(
                accessibility.get("nodes"), list
            ):
                raise ControlError("browser_diagnostic_document_invalid")
            if (
                len(json.dumps([document, accessibility], allow_nan=False).encode())
                > MAX_BYTES
            ):
                raise ControlError("browser_diagnostic_too_large")
            layout = await read("Page.getLayoutMetrics")
            size = layout.get("cssContentSize", layout.get("contentSize", {}))
            if any(
                type(size.get(k)) not in (int, float)
                or not math.isfinite(size[k])
                or size[k] <= 0
                for k in ("width", "height")
            ):
                raise ControlError("browser_diagnostic_dimensions_invalid")
            width, height = math.ceil(size["width"]), math.ceil(size["height"])
            if width * height > MAX_CSS_PIXELS:
                raise ControlError("browser_diagnostic_too_large")
            screenshot = await read(
                "Page.captureScreenshot",
                {
                    "format": "png",
                    "captureBeyondViewport": True,
                    "fromSurface": True,
                    "clip": {
                        "x": 0,
                        "y": 0,
                        "width": width,
                        "height": height,
                        "scale": 1,
                    },
                },
            )
            data = screenshot.get("data")
            if not isinstance(data, str):
                raise ControlError("browser_diagnostic_image_invalid")
            pixels = await asyncio.to_thread(_image_size, data, width, height)
            await current()
            return {
                "activeTargetId": target,
                "controlEpoch": epoch,
                "targetEpoch": target_epoch,
                "frames": frames,
                "dom": document["root"],
                "accessibility": accessibility["nodes"],
                "screenshot": {
                    "format": "png",
                    "data": data,
                    "width": pixels[0],
                    "height": pixels[1],
                    "cssWidth": width,
                    "cssHeight": height,
                    "fullPage": True,
                },
            }
        finally:
            page.remove_event_handler(source_event)

    return cast(
        dict[str, Any],
        await control.run(
            "ai",
            epoch,
            target_epoch,
            capture,
            observation=True,
            before_effect=before_read,
        ),
    )
