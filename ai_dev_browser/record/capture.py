"""Bounded semantic capture on existing SDK page connections.

The host retains the original principal and supplies current frame/read
assertions. Browser IDs, origins and recorded events are resource data, never
credentials or grants. This class creates no browser or CDP connection.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
from typing import Any, Protocol

from ..remote.control import ControlError, check_effect_authorization
from .models import PrivacySettings
from .privacy import redact_event

Assertion = Callable[[], Awaitable[None]]
FrameAssertions = Callable[[str, str, int, str, str], Awaitable[Assertion]]
EventHandler = Callable[[str, dict[str, Any]], None]


class PageConnection(Protocol):
    """The existing SDK CDP view transport; no endpoint/reconnect fallback."""

    disconnected: bool
    reader: asyncio.Future[Any]

    async def call(
        self, method: str, params: dict[str, Any] | None = None, timeout: float = 20
    ) -> dict[str, Any]: ...

    def add_event_handler(self, handler: EventHandler) -> None: ...

    def remove_event_handler(self, handler: EventHandler) -> bool: ...


@dataclass
class _Frame:
    frame_id: str
    context_id: int
    unique_id: str
    origin: str
    is_top: bool
    assertion: Assertion
    event_nonce: str = field(default_factory=lambda: secrets.token_hex(24))
    last_sequence: int = 0
    started: bool = False


@dataclass
class _Source:
    target_id: str
    page: PageConnection
    authorize: FrameAssertions
    world: str
    binding: str
    nonce: str
    ready: asyncio.Event
    started: asyncio.Future[None]
    root_frame: str = ""
    handler: EventHandler | None = None
    script_id: str | None = None
    script_requested: bool = False
    binding_requested: bool = False
    accepting: bool = True
    disposing: bool = False
    contexts: dict[int, tuple[str, str, str]] = field(default_factory=dict)
    frames: dict[str, _Frame] = field(default_factory=dict)
    pending_navigation: dict[str, str] = field(default_factory=dict)
    watcher: asyncio.Task[None] | None = None


class EventRecording:
    """Capture only after the host admits each isolated frame context.

    authorize_frame(target_id, frame_id, context_id, context_unique_id, origin)
    must return a
    current async None-or-raise assertion bound to the SAME held principal.
    It checks the real allocation, full source/action grant and content/DLP
    policy independently of these IDs/page facts. Each event rechecks it.
    The read assertion supplied to snapshot is a separate current assertion
    for the captured recording and ALL its sources; it needs no Agent/Ready.
    """

    def __init__(
        self,
        recording_id: str,
        *,
        privacy: PrivacySettings | None = None,
        max_events: int = 10_000,
        max_bytes: int = 4 * 1024 * 1024,
        max_sources: int = 128,
        max_contexts: int = 64,
        show_indicator: bool = True,
    ) -> None:
        if (
            not isinstance(recording_id, str)
            or not 1 <= len(recording_id.encode("utf-8")) <= 128
            or any(ord(char) < 32 for char in recording_id)
        ):
            raise ValueError("Invalid recording identity")
        for value in (max_events, max_bytes, max_sources, max_contexts):
            if type(value) is not int or value < 1:
                raise ValueError("Positive recording limits required")
        if type(show_indicator) is not bool:
            raise ValueError("Explicit recording indicator mode required")
        if privacy is not None and not isinstance(privacy, PrivacySettings):
            raise ValueError("Invalid recording privacy policy")
        self.recording_id = recording_id
        self.privacy = privacy.model_copy(deep=True) if privacy else PrivacySettings()
        self.max_events, self.max_bytes = max_events, max_bytes
        self.max_sources, self.max_contexts = max_sources, max_contexts
        self.show_indicator = show_indicator
        self._events: list[dict[str, Any]] = []
        self._bytes = 0
        self._sources: dict[str, _Source] = {}
        self._history: list[_Source] = []
        self._visited: set[str] = set()
        self._queue: asyncio.Queue[tuple[str, _Source, dict[str, Any]]] = asyncio.Queue(
            128
        )
        self._consumer: asyncio.Task[None] | None = None
        self._lifecycle = asyncio.Lock()
        self._close_task: asyncio.Task[dict[str, Any]] | None = None
        self._closing = False
        self._stopped = False
        self.error: str | None = None
        self.cleanup_uncertain = False

    def status(self) -> dict[str, Any]:
        return {
            "recordingId": self.recording_id,
            "status": (
                "failed"
                if self.error
                else "stopped"
                if self._stopped
                else "stopping"
                if self._closing
                else "recording"
                if self._visited
                else "starting"
            ),
            "events": len(self._events),
            "sources": len(self._visited),
            "error": self.error,
            "cleanupUncertain": self.cleanup_uncertain,
        }

    def source_scopes(self) -> list[dict[str, Any]]:
        """Private host provenance for a fresh full recording-read assertion."""
        return [
            {
                "targetId": source.target_id,
                "frameId": frame.frame_id,
                "contextId": frame.context_id,
                "contextUniqueId": frame.unique_id,
                "origin": frame.origin,
            }
            for source in self._history
            for frame in source.frames.values()
        ]

    @staticmethod
    def _require(assertion: Any) -> None:
        if not callable(assertion):
            raise ControlError(
                "browser_authorization_required"
                if assertion is None
                else "invalid_browser_authorization"
            )

    def _fail(self, code: str) -> None:
        self.error = self.error or code
        for source in self._history:
            if not source.started.done():
                source.started.set_exception(ControlError(self.error))
        if self._close_task is None:
            self._closing = True
            self._close_task = asyncio.create_task(self._finish())

    def _source_code(self, source: _Source) -> str:
        config = {
            "recordingId": self.recording_id,
            "targetId": source.target_id,
            "bindingName": source.binding,
            "nonce": source.nonce,
            "inputPolicy": self.privacy.input_policy,
            "urlQueryPolicy": self.privacy.url_query_policy,
            "showIndicator": self.show_indicator,
        }
        return (
            "globalThis.__ADB_RECORD_CONFIG__ = "
            + json.dumps(config)
            + ";\n"
            + Path(__file__).with_name("capture.js").read_text(encoding="utf-8")
        )

    def _enqueue(self, kind: str, source: _Source, value: dict[str, Any]) -> None:
        if not source.accepting or self.error:
            return
        try:
            self._queue.put_nowait((kind, source, copy.deepcopy(value)))
        except asyncio.QueueFull:
            self._fail("browser_recording_overloaded")

    def _receive(self, source: _Source, method: str, params: dict[str, Any]) -> None:
        # This synchronous observer must never break the owner's CDP reader.
        try:
            if not source.accepting or not isinstance(params, dict):
                return
            if method == "Runtime.executionContextCreated":
                context = params.get("context", {})
                if context.get("name") != source.world:
                    return
                identity = context.get("id")
                unique_id = context.get("uniqueId")
                frame = context.get("auxData", {}).get("frameId")
                origin = context.get("origin", "")
                if (
                    type(identity) is not int
                    or not isinstance(unique_id, str)
                    or not 1 <= len(unique_id) <= 256
                    or not isinstance(frame, str)
                    or not 1 <= len(frame) <= 256
                    or not isinstance(origin, str)
                    or len(origin.encode("utf-8")) > 4096
                ):
                    self._fail("browser_recording_context_invalid")
                    return
                if (
                    len(source.contexts) >= self.max_contexts
                    and identity not in source.contexts
                ):
                    self._fail("browser_recording_context_limit")
                    return
                source.contexts[identity] = (frame, origin, unique_id)
                self._enqueue("context", source, context)
            elif method == "Runtime.executionContextDestroyed":
                identity = params.get("executionContextId")
                if type(identity) is not int:
                    self._fail("browser_recording_context_invalid")
                    return
                current = source.contexts.get(identity)
                unique_id = params.get("executionContextUniqueId")
                if current and (unique_id is None or unique_id == current[2]):
                    source.contexts.pop(identity, None)
            elif method == "Runtime.executionContextsCleared":
                source.contexts.clear()
            elif (
                method == "Runtime.bindingCalled"
                and params.get("name") == source.binding
            ):
                raw = params.get("payload")
                if not isinstance(raw, str) or len(raw.encode("utf-8")) > 64 * 1024:
                    self._fail("browser_recording_event_invalid")
                    return
                identity = params.get("executionContextId")
                if type(identity) is not int:
                    self._fail("browser_recording_context_invalid")
                    return
                context = source.contexts.get(identity)
                if context:
                    # Capture native provenance before queueing. A payload
                    # cannot select another document when numeric IDs recycle.
                    self._enqueue(
                        "binding",
                        source,
                        {**params, "_recordContextUniqueId": context[2]},
                    )
            elif method == "Page.frameNavigated":
                frame = params.get("frame", {})
                if isinstance(frame.get("id"), str) and isinstance(
                    frame.get("url"), str
                ):
                    if (
                        len(frame["id"]) > 256
                        or len(frame["url"].encode("utf-8")) > 8192
                        or (
                            frame["id"] not in source.pending_navigation
                            and len(source.pending_navigation) >= self.max_contexts
                        )
                    ):
                        self._fail("browser_recording_context_limit")
                        return
                    source.pending_navigation[frame["id"]] = frame["url"]
                    if not frame.get("parentId"):
                        source.root_frame = frame["id"]
            elif method == "Page.navigatedWithinDocument":
                context = next(
                    (
                        value
                        for value in source.contexts.values()
                        if value[0] == params.get("frameId")
                    ),
                    None,
                )
                if context:
                    self._enqueue(
                        "navigation",
                        source,
                        {**params, "_recordContextUniqueId": context[2]},
                    )
        except Exception:
            self._fail("browser_recording_event_invalid")

    async def _assert_frame(
        self, source: _Source, identity: int, frame_id: str, unique_id: str, origin: str
    ) -> _Frame:
        try:
            assertion = await source.authorize(
                source.target_id, frame_id, identity, unique_id, origin
            )
        except PermissionError:
            raise ControlError("browser_authorization_denied") from None
        except Exception:
            raise ControlError("browser_authorization_unavailable") from None
        if not callable(assertion):
            raise ControlError("invalid_browser_authorization")
        await check_effect_authorization(assertion)
        return _Frame(
            frame_id,
            identity,
            unique_id,
            origin,
            frame_id == source.root_frame,
            assertion,
        )

    async def attach_source(
        self,
        target_id: str,
        page: PageConnection,
        *,
        before_effect: Assertion,
        authorize_frame: FrameAssertions,
    ) -> dict[str, Any]:
        """Use when recording an authorized page; return after its recorder is active.

        Reuse the caller's existing SDK CDP page. Attach each additional target
        explicitly. This captures semantic events for build_recording_draft;
        use core.page_record_start for a visual GIF. Input continues through
        the existing SDK or human browser. This method creates no browser.

        Args:
            target_id: Exact target already selected and admitted by the host.
            page: Its existing page connection, with additive event observers.
            before_effect: Current async None-or-raise source assertion.
            authorize_frame: Async factory receiving target, frame, numeric
                context, native unique context and origin. It must return a
                current assertion bound to the original authenticated caller.

        Returns:
            Recording status and event/source counts, with status=recording.

        Failure:
            Fix the source or current authority before starting a new recording.
            A failed recording cannot provide a partial successful workflow.
            Closing capture retires only its instrumentation; keep the page open.
        """
        self._require(before_effect)
        self._require(authorize_frame)
        if not isinstance(target_id, str) or not target_id or len(target_id) > 256:
            raise ControlError("invalid_browser_target")
        # Keep initialization owned even if its caller disappears after a CDP
        # registration was sent. Drain it, then remove exactly those resources.
        pending = asyncio.create_task(
            self._install_source(target_id, page, before_effect, authorize_frame)
        )
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError:
            while not pending.done():
                try:
                    await asyncio.shield(pending)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            self._fail("browser_recording_start_cancelled")
            await self.close()
            raise
        except Exception as error:
            code = (
                error.code
                if isinstance(error, ControlError)
                else "browser_recording_start_failed"
            )
            self._fail(code)
            await self.close()
            raise ControlError(code) from None
        return self.status()

    async def _install_source(
        self,
        target_id: str,
        page: PageConnection,
        before_effect: Assertion,
        authorize_frame: FrameAssertions,
    ) -> None:
        async with self._lifecycle:
            if self._closing or self.error:
                raise ControlError(self.error or "browser_recording_stopped")
            if target_id in self._sources:
                raise ControlError("browser_recording_source_attached")
            if len(self._history) >= self.max_sources:
                raise ControlError("browser_recording_source_limit")
            await check_effect_authorization(before_effect)
            if page.disconnected:
                raise ControlError("browser_recording_disconnected")
            token = secrets.token_hex(12)
            started: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            started.add_done_callback(
                lambda done: None if done.cancelled() else done.exception()
            )
            source = _Source(
                target_id,
                page,
                authorize_frame,
                "adb-record-" + token,
                "__adb_record_" + token,
                secrets.token_hex(24),
                asyncio.Event(),
                started,
            )
            self._sources[target_id] = source
            self._history.append(source)
            source.handler = lambda method, params: self._receive(
                source, method, params
            )
            page.add_event_handler(source.handler)
            if self._consumer is None:
                self._consumer = asyncio.create_task(self._consume())
            source.watcher = asyncio.create_task(self._watch_source(source))
            try:
                for method in ("Runtime.enable", "Page.enable"):
                    await check_effect_authorization(before_effect)
                    await page.call(method)
                await check_effect_authorization(before_effect)
                tree = await page.call("Page.getFrameTree")
                root = tree.get("frameTree", {}).get("frame", {})
                source.root_frame = root.get("id", "")
                if not isinstance(source.root_frame, str) or not source.root_frame:
                    raise ControlError("browser_recording_frame_unavailable")
                await check_effect_authorization(before_effect)
                source.binding_requested = True
                await page.call(
                    "Runtime.addBinding",
                    {
                        "name": source.binding,
                        "executionContextName": source.world,
                    },
                )
                await check_effect_authorization(before_effect)
                world = await page.call(
                    "Page.createIsolatedWorld",
                    {
                        "frameId": source.root_frame,
                        "worldName": source.world,
                        "grantUniveralAccess": False,
                    },
                )
                identity = world.get("executionContextId")
                if type(identity) is not int:
                    raise ControlError("browser_recording_context_invalid")
                context = source.contexts.get(identity)
                if context is None or context[0] != source.root_frame:
                    raise ControlError("browser_recording_context_invalid")
                _, origin, unique_id = context
                source.frames[unique_id] = await self._assert_frame(
                    source, identity, source.root_frame, unique_id, origin
                )
                self._enqueue(
                    "context",
                    source,
                    {
                        "id": identity,
                        "uniqueId": unique_id,
                        "name": source.world,
                        "origin": origin,
                        "auxData": {"frameId": source.root_frame},
                    },
                )
                await check_effect_authorization(before_effect)
                source.script_requested = True
                installed = await page.call(
                    "Page.addScriptToEvaluateOnNewDocument",
                    {
                        "source": self._source_code(source),
                        "worldName": source.world,
                        "runImmediately": True,
                    },
                )
                source.script_id = installed.get("identifier")
                if not isinstance(source.script_id, str) or not source.script_id:
                    raise ControlError("browser_recording_script_unconfirmed")
            finally:
                source.ready.set()
        await asyncio.wait_for(asyncio.shield(source.started), 20)
        if self.error:
            raise ControlError(self.error)

    async def _watch_source(self, source: _Source) -> None:
        try:
            await asyncio.shield(source.page.reader)
        except asyncio.CancelledError:
            if source.disposing:
                return
        except Exception:
            pass
        if not source.disposing:
            self._fail("browser_recording_disconnected")

    def _append(self, source: _Source, frame: _Frame, event: dict[str, Any]) -> None:
        event = copy.deepcopy(event)
        event.update(targetId=source.target_id, frameId=frame.frame_id)
        page = dict(event.get("page") or {})
        page.update(
            targetId=source.target_id, frameId=frame.frame_id, origin=frame.origin
        )
        event["page"] = page
        if isinstance(event.get("target"), dict):
            target = dict(event["target"])
            target["framePath"] = [] if frame.is_top else [frame.origin]
            event["target"] = target
        event = redact_event(event, self.privacy)
        event["seq"] = len(self._events) + 1
        event["receivedAt"] = datetime.now(timezone.utc).isoformat()
        encoded = json.dumps(event, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if (
            len(self._events) >= self.max_events
            or self._bytes + len(encoded) > self.max_bytes
        ):
            raise ControlError("browser_recording_limit")
        self._events.append(event)
        self._bytes += len(encoded)

    async def _context(self, source: _Source, context: dict[str, Any]) -> None:
        identity = context["id"]
        unique_id = context["uniqueId"]
        current = source.contexts.get(identity)
        if current is None or current[2] != unique_id or source.disposing:
            return
        frame_id, origin, _ = current
        frame = source.frames.get(unique_id)
        if frame is None:
            if len(source.frames) >= self.max_contexts:
                raise ControlError("browser_recording_context_limit")
            frame = await self._assert_frame(
                source, identity, frame_id, unique_id, origin
            )
            source.frames[unique_id] = frame
        if frame.started:
            return
        await check_effect_authorization(frame.assertion)
        if source.contexts.get(identity) != current or source.disposing:
            return
        result = await source.page.call(
            "Runtime.evaluate",
            {
                "expression": self._source_code(source)
                + "\nglobalThis.__adbSemanticRecorder.start("
                + json.dumps(frame.event_nonce)
                + ");",
                "uniqueContextId": unique_id,
                "returnByValue": True,
            },
        )
        if "exceptionDetails" in result:
            raise ControlError("browser_recording_script_failed")
        frame.started = True

    async def _binding(self, source: _Source, params: dict[str, Any]) -> None:
        identity = params.get("executionContextId")
        if type(identity) is not int:
            raise ControlError("browser_recording_context_invalid")
        unique_id = params.get("_recordContextUniqueId")
        current = source.contexts.get(identity)
        if current is None or current[2] != unique_id:
            return
        frame = source.frames.get(unique_id)
        if frame is None:
            return  # A main/page world or other binding never gains frame admission.
        raw = params.get("payload")
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > 64 * 1024:
            raise ControlError("browser_recording_event_invalid")
        payload = json.loads(
            raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError())
        )
        if (
            not isinstance(payload, dict)
            or payload.get("nonce") != source.nonce
            or payload.get("contextNonce") != frame.event_nonce
        ):
            return
        if payload.get("schemaVersion") != "1.0" or not isinstance(
            payload.get("event"), dict
        ):
            raise ControlError("browser_recording_event_invalid")
        event = payload["event"]
        sequence = event.get("localSeq")
        if type(sequence) is not int or sequence < 1:
            raise ControlError("browser_recording_event_invalid")
        if sequence <= frame.last_sequence:
            return
        if sequence != frame.last_sequence + 1:
            raise ControlError("browser_recording_event_gap")
        if sequence == 1 and event.get("kind") != "recorder_installed":
            raise ControlError("browser_recording_event_gap")
        if not isinstance(event.get("kind"), str):
            raise ControlError("browser_recording_event_invalid")
        for key in ("page", "target"):
            if event.get(key) is not None and not isinstance(event[key], dict):
                raise ControlError("browser_recording_event_invalid")
        await check_effect_authorization(frame.assertion)
        if source.contexts.get(identity) != current:
            return
        frame.last_sequence = sequence
        if event["kind"] == "recorder_installed":
            navigation = source.pending_navigation.pop(frame.frame_id, None)
            if navigation:
                self._append(
                    source,
                    frame,
                    {
                        "kind": "navigation" if frame.is_top else "frame_navigation",
                        "urlAfter": navigation,
                    },
                )
            if not frame.is_top:
                event = {**event, "kind": "frame_installed"}
            elif source.target_id not in self._visited:
                if self._visited:
                    self._append(
                        source,
                        frame,
                        {
                            "kind": "page_opened",
                            "url": event.get("page", {}).get("url", ""),
                        },
                    )
                self._visited.add(source.target_id)
        self._append(source, frame, event)
        if (
            frame.is_top
            and event["kind"] == "recorder_installed"
            and not source.started.done()
        ):
            source.started.set_result(None)

    async def _navigation(self, source: _Source, params: dict[str, Any]) -> None:
        frame_id, url = params.get("frameId"), params.get("url")
        if not isinstance(frame_id, str) or not isinstance(url, str):
            raise ControlError("browser_recording_event_invalid")
        unique_id = params.get("_recordContextUniqueId")
        if not isinstance(unique_id, str):
            return
        frame = source.frames.get(unique_id)
        if frame is None or frame.frame_id != frame_id:
            return
        current = source.contexts.get(frame.context_id)
        if current is None or current[2] != frame.unique_id:
            return
        await check_effect_authorization(frame.assertion)
        if source.contexts.get(frame.context_id) != current:
            return
        self._append(
            source,
            frame,
            {
                "kind": "navigation" if frame.is_top else "frame_navigation",
                "urlAfter": url,
            },
        )

    async def _consume(self) -> None:
        while True:
            kind, source, value = await self._queue.get()
            try:
                await source.ready.wait()
                if not self.error:
                    if kind == "context":
                        await self._context(source, value)
                    elif kind == "binding":
                        await self._binding(source, value)
                    elif kind == "navigation":
                        await self._navigation(source, value)
            except ControlError as error:
                self._fail(error.code)
            except Exception:
                self._fail("browser_recording_event_invalid")
            finally:
                self._queue.task_done()

    async def _cleanup_commands(self, source: _Source) -> None:
        if source.script_id:
            await source.page.call(
                "Page.removeScriptToEvaluateOnNewDocument",
                {"identifier": source.script_id},
            )
        elif source.script_requested:
            self.cleanup_uncertain = True
        for identity, context in list(source.contexts.items()):
            flush = False
            unique_id = context[2]
            frame = source.frames.get(unique_id)
            if frame and not self.error:
                try:
                    await check_effect_authorization(frame.assertion)
                    flush = True
                except ControlError as error:
                    self._fail(error.code)
            if source.contexts.get(identity) == context:
                await source.page.call(
                    "Runtime.evaluate",
                    {
                        "expression": f"globalThis.__adbSemanticRecorder?.stop({str(flush).lower()});",
                        "uniqueContextId": unique_id,
                        "returnByValue": True,
                    },
                )
        if source.binding_requested:
            await source.page.call("Runtime.removeBinding", {"name": source.binding})

    async def _cleanup_source(self, source: _Source) -> None:
        source.disposing = True
        if source.watcher:
            source.watcher.cancel()
            await asyncio.gather(source.watcher, return_exceptions=True)
        try:
            if source.page.disconnected:
                self.cleanup_uncertain = True
            else:
                # One bounded retirement, rather than N sequential transport
                # deadlines when a dialog or dead peer blocks every frame.
                await asyncio.wait_for(self._cleanup_commands(source), 20)
        except Exception:
            self.cleanup_uncertain = True
        finally:
            source.accepting = False
            if source.handler:
                source.page.remove_event_handler(source.handler)

    async def detach_source(self, target_id: str) -> dict[str, Any]:
        async with self._lifecycle:
            source = self._sources.pop(target_id, None)
            if source:
                await self._cleanup_source(source)
        try:
            await asyncio.wait_for(self._queue.join(), 20)
        except asyncio.TimeoutError:
            self._fail("browser_authorization_unavailable")
        if self.cleanup_uncertain:
            self._fail("browser_recording_cleanup_uncertain")
        return self.status()

    async def drain(self) -> None:
        await asyncio.wait_for(self._queue.join(), 20)
        if self.error:
            raise ControlError(self.error)

    async def snapshot(self, *, before_read: Assertion) -> dict[str, Any]:
        """Use when exporting captured events; return a detached, authorized snapshot.

        Call close first to flush the final pending input and obtain a complete
        recording. While capture is active, this returns events received so far.
        Pass events to build_recording_draft for steps and a reviewable Skill.

        Args:
            before_read: Current async None-or-raise assertion covering this
                recording and every source in source_scopes, independently of
                whether any Agent is running. The host owns access and retention.

        Returns:
            recordingId and events; no files are written or Skills installed.

        Failure:
            Recheck the original caller's current recording/source access.
            A changed scope or failed capture refuses rather than returning
            an incomplete successful recording.
        """
        self._require(before_read)
        scopes = self.source_scopes()
        await check_effect_authorization(before_read)
        await self.drain()
        if self.source_scopes() != scopes:
            raise ControlError("browser_recording_sources_changed")
        value = {
            "recordingId": self.recording_id,
            "events": copy.deepcopy(self._events),
        }
        await check_effect_authorization(before_read)
        if self.source_scopes() != scopes:
            raise ControlError("browser_recording_sources_changed")
        return value

    async def _finish(self) -> dict[str, Any]:
        self._closing = True
        async with self._lifecycle:
            for source in self._history:
                source.ready.set()
                if source.accepting:
                    await self._cleanup_source(source)
            self._sources.clear()
        try:
            await asyncio.wait_for(self._queue.join(), 20)
        except asyncio.TimeoutError:
            self.error = self.error or "browser_authorization_unavailable"
        if self._consumer:
            self._consumer.cancel()
            await asyncio.gather(self._consumer, return_exceptions=True)
        if self.cleanup_uncertain:
            self.error = self.error or "browser_recording_cleanup_uncertain"
        self._stopped = True
        return self.status()

    async def close(self) -> dict[str, Any]:
        """Retire owned instrumentation; never close the page/browser itself."""
        if self._close_task is None:
            self._closing = True
            self._close_task = asyncio.create_task(self._finish())
        try:
            return await asyncio.shield(self._close_task)
        except asyncio.CancelledError:
            while not self._close_task.done():
                try:
                    await asyncio.shield(self._close_task)
                except asyncio.CancelledError:
                    continue
            raise
