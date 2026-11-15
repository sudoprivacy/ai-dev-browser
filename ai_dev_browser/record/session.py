"""Recording lifecycle on an existing session and a host-owned durable sink."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import copy
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from ..remote.control import ControlError, check_effect_authorization
from .capture import Assertion, EventRecording, FrameAssertions
from .draft import build_recording_draft
from .models import PrivacySettings

Persist = Callable[[dict[str, Any]], Awaitable[object]]
Reconcile = Callable[[dict[str, Any], str], Awaitable[object]]


def _require(callback: Any, code: str) -> None:
    if not callable(callback):
        raise ControlError(code)


class SessionRecording:
    """One original owner, capture and persist-before-result transition.

    The host owns the store and its current writer/exclusion checks. Callbacks
    receive detached data, never confer access from recording IDs or digests,
    and must return None only after their actual durable work is confirmed.
    """

    def __init__(
        self,
        recording_id: str,
        owner: str,
        *,
        before_capture: Assertion,
        authorize_frame: FrameAssertions,
        before_read: Assertion,
        persist: Persist,
        reconcile: Reconcile | None = None,
        privacy: PrivacySettings | None = None,
    ) -> None:
        for callback in (before_capture, authorize_frame, before_read):
            _require(callback, "browser_authorization_required")
        _require(persist, "browser_recording_store_required")
        if reconcile is not None:
            _require(reconcile, "browser_recording_store_required")
        self.capture = EventRecording(recording_id, privacy=privacy)
        self.owner = owner
        self.before_capture = before_capture
        self.authorize_frame = authorize_frame
        self.before_read = before_read
        self.persist, self.reconcile = persist, reconcile
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.phase = "recording"
        self.error: str | None = None
        self.current: tuple[str, Any] | None = None
        self._terminal: dict[str, Any] | None = None
        self._digest: str | None = None
        self._commit_task: asyncio.Task[None] | None = None
        self._recovery = asyncio.Lock()

    def status(self) -> dict[str, Any]:
        return {
            **self.capture.status(),
            "storageStatus": self.phase,
            "storageError": self.error,
            "hasDraft": bool(self._terminal and self._terminal.get("draft")),
        }

    def assert_owner(self, actor: str) -> None:
        if actor != self.owner:
            raise ControlError("browser_recording_not_owned")

    async def attach(self, target_id: str, page: Any) -> None:
        if self.phase != "recording" or self.current == (target_id, page):
            return
        await self.capture.attach_source(
            target_id,
            page,
            before_effect=self.before_capture,
            authorize_frame=self.authorize_frame,
        )
        self.current = (target_id, page)

    async def detach(self) -> None:
        if self.current is not None:
            target, _ = self.current
            result = await self.capture.detach_source(target)
            self.current = None
            if result["status"] == "failed":
                raise ControlError(result["error"] or "browser_recording_interrupted")

    async def prepare_input(self, target_id: str, page: Any) -> None:
        """Do not send SDK input through a new document's admission gap."""
        if self.phase != "recording":
            return
        deadline = asyncio.get_running_loop().time() + 20
        while True:
            await self.capture.drain()
            if self.current != (target_id, page):
                raise ControlError("browser_recording_source_changed")
            tree = await page.call("Page.getFrameTree")
            frame_ids = []

            def collect(node: dict[str, Any]) -> None:
                frame_ids.append(node["frame"]["id"])
                if len(frame_ids) > self.capture.max_contexts:
                    raise ControlError("browser_recording_context_limit")
                for child in node.get("childFrames", []):
                    collect(child)

            collect(tree["frameTree"])
            await self.capture.drain()
            source = self.capture._sources.get(target_id)
            if source is None or source.page is not page:
                raise ControlError("browser_recording_source_changed")
            contexts = dict(source.contexts)
            ready = []
            for _, (frame_id, _, unique_id) in contexts.items():
                frame = source.frames.get(unique_id)
                if (
                    frame_id in frame_ids
                    and frame is not None
                    and frame.started
                    and frame.last_sequence
                ):
                    ready.append(frame)
            if set(frame_ids) <= {frame.frame_id for frame in ready}:
                for frame in ready:
                    try:
                        await check_effect_authorization(frame.assertion)
                    except ControlError as error:
                        self.capture._fail(error.code)
                        raise
                if source.contexts == contexts:
                    return
            if asyncio.get_running_loop().time() >= deadline:
                raise ControlError("browser_recording_context_unavailable")
            await asyncio.sleep(0.01)

    async def _commit(self) -> None:
        closed = await self.capture.close()
        self.current = None
        self.phase = "pending-save"
        snapshot = None
        draft = None
        draft_error = None
        if closed["status"] != "failed":
            try:
                snapshot = await self.capture.snapshot(before_read=self.before_read)
                draft = build_recording_draft(
                    self.capture.recording_id,
                    snapshot["events"],
                    privacy=self.capture.privacy,
                )
            except ControlError as error:
                closed = {**closed, "status": "failed", "error": error.code}
                snapshot = None
            except ValueError:
                # Preserve the actual raw recording if a later explicit file
                # input binding or draft review is required. Never drop that
                # event and silently publish an incomplete replay workflow.
                draft_error = "browser_recording_draft_requires_review"
        self._terminal = {
            "recordingId": self.capture.recording_id,
            "createdAt": self.created_at,
            "endedAt": datetime.now(timezone.utc).isoformat(),
            "status": closed["status"],
            "error": closed["error"],
            "snapshot": snapshot,
            "draft": draft,
            "draftError": draft_error,
            "sources": self.capture.source_scopes(),
        }
        encoded = json.dumps(
            self._terminal,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        self._digest = hashlib.sha256(encoded).hexdigest()
        try:
            result = await self.persist(copy.deepcopy(self._terminal))
            if result is not None:
                raise ControlError("invalid_browser_recording_store")
        except BaseException:
            self.phase = "storage-unknown"
            self.error = "browser_recording_write_unconfirmed"
            raise
        self.phase = "saved"

    async def _wait_commit(self) -> None:
        assert self._commit_task is not None
        try:
            await asyncio.shield(self._commit_task)
        except asyncio.CancelledError:
            # Every caller, including concurrent Stop and cleanup, retains
            # this original write's barrier until its outcome is known.
            while not self._commit_task.done():
                try:
                    await asyncio.shield(self._commit_task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            raise
        except Exception:
            raise ControlError("browser_recording_write_unconfirmed") from None

    async def finish(
        self, actor: str, *, before_read: Assertion, reconcile: Reconcile | None = None
    ) -> dict[str, Any]:
        self.assert_owner(actor)
        _require(before_read, "browser_authorization_required")
        await check_effect_authorization(before_read)
        if self._commit_task is None:
            self._commit_task = asyncio.create_task(self._commit())
            self._commit_task.add_done_callback(
                lambda done: None if done.cancelled() else done.exception()
            )
            await self._wait_commit()
        elif not self._commit_task.done():
            await self._wait_commit()
        if self.phase == "storage-unknown":
            # Read reconciliation only. This callback must prove the exact
            # original terminal payload already exists durably. No second
            # persistence call is issued, including after token revalidation.
            async with self._recovery:
                if self.phase == "storage-unknown":
                    resolver = reconcile or self.reconcile
                    if (
                        resolver is None
                        or self._terminal is None
                        or self._digest is None
                    ):
                        raise ControlError("browser_recording_write_unconfirmed")
                    await check_effect_authorization(before_read)
                    try:
                        result = await resolver(
                            copy.deepcopy(self._terminal), self._digest
                        )
                        if result is not None:
                            raise ControlError("invalid_browser_recording_store")
                    except Exception:
                        raise ControlError(
                            "browser_recording_write_unconfirmed"
                        ) from None
                    self.phase = "saved"
                    self.error = None
        try:
            await check_effect_authorization(before_read)
        except ControlError:
            if self.phase == "saved":
                raise ControlError("browser_recording_write_unconfirmed") from None
            raise
        return self.status()

    async def interrupt(self) -> None:
        if self.phase == "recording":
            self.capture._fail("browser_recording_interrupted")
            # Terminal metadata only; failed capture cannot expose a partial
            # event stream as a successful recording or workflow.
            if self._commit_task is None:
                self._commit_task = asyncio.create_task(self._commit())
                self._commit_task.add_done_callback(
                    lambda done: None if done.cancelled() else done.exception()
                )
            await self._wait_commit()
        elif self._commit_task is not None and not self._commit_task.done():
            await self._wait_commit()
        if self.phase == "storage-unknown":
            raise ControlError("browser_recording_write_unconfirmed")
