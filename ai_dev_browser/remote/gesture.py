"""An acknowledged live gesture held inside one browser input barrier."""

import asyncio
import math
from contextlib import suppress

from .control import ControlError


class LiveDrag:
    """One bounded producer; a disconnect releases input, never grants AI control.

    The host authenticates every packet and binds its controller, viewer and
    epochs. The operation lock remains held from press through the final release.
    No packet is replayed. An abandoned client cannot leave a mouse button down.
    """

    def __init__(
        self, control, controller, epoch, target_epoch, view, point, *, on_finish=None
    ):
        self.control, self.controller = control, controller
        self.epoch, self.target_epoch = epoch, target_epoch
        self.view, self.point = view, point
        self.queue = asyncio.Queue(maxsize=1)
        self.ready = asyncio.get_running_loop().create_future()
        self.ready.add_done_callback(
            lambda done: None if done.cancelled() else done.exception()
        )
        self.task = None
        self.sending = False
        self.closed = False
        self.on_finish = on_finish

    async def start(self):
        self.task = asyncio.create_task(
            self.control.run(
                self.controller, self.epoch, self.target_epoch, self._perform
            )
        )
        # Retrieve errors even if the HTTP client has disappeared. They still
        # propagate to start/send; they must not become unobserved task errors.
        self.task.add_done_callback(self._finished)
        await asyncio.shield(self.ready)

    def _finished(self, task):
        self.closed = True
        error = (
            ControlError("browser_drag_interrupted")
            if task.cancelled()
            else task.exception()
        )
        if not self.ready.done():
            self.ready.set_exception(error or ControlError("browser_drag_closed"))
        while not self.queue.empty():
            _, _, acknowledged = self.queue.get_nowait()
            if not acknowledged.done():
                acknowledged.set_exception(error or ControlError("browser_drag_closed"))
        if self.on_finish is not None:
            self.on_finish()

    async def _perform(self):
        acknowledged = None
        failure = None
        first_motion = True
        cancelled = False
        try:
            await self.view.press(self.point)
            self.ready.set_result(None)
            # This is an input cleanup bound, never human consent or a return
            # to AI. The control state and its owner survive an expired gesture.
            deadline = asyncio.get_running_loop().time() + 30
            while True:
                phase, point, acknowledged = await asyncio.wait_for(
                    self.queue.get(),
                    max(0, min(5, deadline - asyncio.get_running_loop().time())),
                )
                self.control._authorize(
                    self.controller, self.epoch, self.target_epoch, False
                )
                if phase != "cancel":
                    if (
                        first_motion
                        and math.hypot(
                            point["x"] - self.point["x"],
                            point["y"] - self.point["y"],
                        )
                        > 16
                    ):
                        # A very fast gesture may coalesce to one endpoint.
                        # Native canvas widgets first arm their drag threshold,
                        # then require another real motion before panning.
                        await self.view.move(
                            {
                                key: (point[key] + self.point[key]) / 2
                                for key in ("x", "y")
                            }
                        )
                        await asyncio.sleep(0.01)
                    await self.view.move(point)
                    first_motion = False
                if phase in ("end", "cancel"):
                    cancelled = phase == "cancel"
                    break
                acknowledged.set_result(None)
                acknowledged = None
        except asyncio.TimeoutError as error:
            failure = ControlError("browser_drag_expired")
            raise failure from error
        except BaseException as error:
            failure = error
            raise
        finally:
            try:
                await self.view.release()
            except BaseException as error:
                failure = error
                # An uncertain release must fence queued writes. Retain the
                # original human owner; no error path grants AI control.
                self.control.state = "error"
                self.control.error = "browser_drag_release_uncertain"
                self.control.epoch += 1
                raise
            finally:
                if (failure or cancelled) and self.control.epoch == self.epoch:
                    # Abandoned/cancelled input cannot unlock queued coordinates
                    # from the old gesture. Keep its human controller unchanged.
                    self.control.epoch += 1
                if acknowledged is not None and not acknowledged.done():
                    if failure:
                        acknowledged.set_exception(failure)
                    else:
                        acknowledged.set_result(None)

    async def send(self, phase, point):
        if self.task.done():
            await self.task
            raise ControlError("browser_drag_closed")
        if self.closed:
            raise ControlError("browser_drag_closed")
        if self.sending:
            raise ControlError("browser_drag_packet_in_progress")
        self.sending = True
        acknowledged = asyncio.get_running_loop().create_future()
        try:
            self.queue.put_nowait((phase, point, acknowledged))
            await asyncio.wait(
                (acknowledged, self.task), return_when=asyncio.FIRST_COMPLETED
            )
            if not acknowledged.done():
                await self.task
                raise ControlError("browser_drag_closed")
            await asyncio.shield(acknowledged)
            if phase in ("end", "cancel"):
                await asyncio.shield(self.task)
        finally:
            if not acknowledged.done():
                # A disconnected caller does not cancel the input driver.
                acknowledged.add_done_callback(
                    lambda done: None if done.cancelled() else done.exception()
                )
            self.sending = False

    async def close(self):
        if self.closed:
            if self.task is not None:
                with suppress(Exception):
                    await asyncio.shield(self.task)
            return
        self.closed = True
        if self.task is not None and not self.task.done():
            # A packet already in progress owns its acknowledgement. Let its
            # bounded driver finish, then the queue accepts the cancellation.
            acknowledged = asyncio.get_running_loop().create_future()
            await self.queue.put(("cancel", None, acknowledged))
            await asyncio.wait(
                (acknowledged, self.task), return_when=asyncio.FIRST_COMPLETED
            )
            if acknowledged.done():
                with suppress(Exception):
                    await asyncio.shield(acknowledged)
            else:
                acknowledged.cancel()
        if self.task is not None:
            with suppress(Exception):
                await asyncio.shield(self.task)
