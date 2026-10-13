"""Serialize browser operations and explicit AI/human control transfers.

The embedding host authenticates callers and isolates the browser endpoint.
Actor IDs below are trusted identities supplied by that host, not client input.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Literal, TypeVar

T = TypeVar("T")
ControlState = Literal["ai", "pausing", "human", "observing", "error"]


class ControlError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class BrowserControl:
    """One lease shared by every agent, target and viewer of a browser.

    New AI operations stop immediately when takeover starts. The existing
    operation drains before human control is granted. Cancellation/failure
    never silently grants AI control. Hosts must not expose a bypass endpoint.
    """

    def __init__(self):
        self.state: ControlState = "ai"
        self.epoch = 0
        self.target_epoch = 0
        self.controller: str | None = None
        self.error: str | None = None
        self._operations = asyncio.Lock()

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "controlEpoch": self.epoch,
            "targetEpoch": self.target_epoch,
            "controller": self.controller,
            "error": self.error,
        }

    def _authorize(self, actor, epoch, target_epoch, observation):
        if epoch != self.epoch or target_epoch != self.target_epoch:
            raise ControlError("stale_browser_operation")
        if observation:
            return
        if actor == "ai" and self.state != "ai":
            raise ControlError("browser_control_held_by_user")
        if actor != "ai" and (self.state != "human" or self.controller != actor):
            raise ControlError("browser_control_not_owned")

    async def run(
        self,
        actor: str,
        epoch: int,
        target_epoch: int,
        operation: Callable[[], Awaitable[T]],
        *,
        observation: bool = False,
    ) -> T:
        """Check epochs again after queueing; never replay a rejected action.

        `observation` is host policy. Only exact, proven read-only operations
        may set it. Arbitrary JS evaluation and lifecycle operations may not.
        Atomic input press/release sequences belong in one operation.
        """
        self._authorize(actor, epoch, target_epoch, observation)
        async with self._operations:
            self._authorize(actor, epoch, target_epoch, observation)
            pending: asyncio.Future[T] = asyncio.ensure_future(operation())
            try:
                return await asyncio.shield(pending)
            except asyncio.CancelledError:
                # A disconnected/canceled caller must not abandon a sent
                # input sequence and release the lock while it still runs.
                # Commands must have their own bounded transport deadlines.
                while not pending.done():
                    try:
                        await asyncio.shield(pending)
                    except asyncio.CancelledError:
                        continue
                pending.result()
                raise

    async def take(self, controller: str) -> dict[str, Any]:
        if not controller or controller == "ai":
            raise ControlError("invalid_browser_controller")
        if self.state == "human" and self.controller == controller:
            return self.snapshot()
        if self.state not in ("ai", "error"):
            raise ControlError("browser_control_transfer_in_progress")
        if self.controller is not None and self.controller != controller:
            raise ControlError("browser_control_not_owned")
        self.state = "pausing"
        self.controller = controller
        self.epoch += 1
        self.error = None
        try:
            async with self._operations:
                self.state = "human"
        except BaseException:
            self.state = "error"
            self.error = "browser_control_transfer_interrupted"
            raise
        return self.snapshot()

    async def give_back(
        self, controller: str, observe: Callable[[], Awaitable[T]]
    ) -> tuple[dict[str, Any], T]:
        if self.state != "human" or self.controller != controller:
            raise ControlError("browser_control_not_owned")
        self.state = "observing"
        self.epoch += 1
        self.error = None
        try:
            async with self._operations:
                observation = await observe()
                self.state = "ai"
                self.controller = None
        except BaseException:
            self.state = "human"
            self.error = "browser_observation_required"
            raise
        return self.snapshot(), observation

    def change_target(self) -> None:
        """Invalidate queued input/frames inside an authorized operation.

        The host calls this only while `run` owns the operation lock, after
        changing the authorized target. It also checks epochs on delivered
        frames so a previously captured image cannot replace the new target.
        """
        self.target_epoch += 1


class SharedViewer:
    """Acquire one display adapter on demand; close it at the last detach.

    The factory/close callbacks own the view only, never Chrome or its profile.
    Frame producers can use the same lifetime. A canceled factory must clean
    its own partially-created resources, as it has not returned ownership yet.
    """

    def __init__(self, create, close):
        self._create = create
        self._close = close
        self._lock = asyncio.Lock()
        self._view = None
        self._owners: set[str] = set()

    async def attach(self, viewer: str):
        if not viewer:
            raise ValueError("Viewer identity required")
        async with self._lock:
            if self._view is None:
                self._view = await self._create()
            self._owners.add(viewer)
            return self._view

    async def detach(self, viewer: str):
        async with self._lock:
            self._owners.discard(viewer)
            if not self._owners and self._view is not None:
                view = self._view
                await self._close(view)
                self._view = None
