"""Trusted host input transactions on the existing session and input barrier.

The host keeps its original held-input journal and translator. Callbacks are
server code, never wire arguments. This module supplies no input schema, user
grant, persistent store, browser, transport connection or automatic recovery.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .cdp import send_command
from .commands import _Commands
from .control import ControlError, check_effect_authorization

Assertion = Callable[[], Awaitable[None]]


@dataclass
class _Scope:
    page: Any
    controller: str
    target: str
    epoch: int
    target_epoch: int
    phase: str = "ready"


class _InputCommands:
    def __init__(
        self, scope: _Scope, check: Assertion, *, cleanup: bool = False
    ) -> None:
        self.scope, self.check, self.cleanup = scope, check, cleanup
        self.active = True
        self.commands = _Commands(scope.page, self._current)

    def _assert_active(self) -> None:
        if not self.active or self.scope.phase != "ready":
            raise ControlError("browser_input_context_closed")

    async def _current(self) -> None:
        self._assert_active()
        await self.check()
        # A host callback can finish while a spawned command awaits authority.
        # Its handle expires with that original invocation's input barrier.
        self._assert_active()

    async def call(
        self, method: str, params: dict[str, Any] | None = None, timeout: float = 20
    ) -> Any:
        self._assert_active()
        params = params or {}
        if self.cleanup:
            key_up = (
                method == "Input.dispatchKeyEvent"
                and params.get("type") == "keyUp"
                and params.keys()
                <= {
                    "type",
                    "key",
                    "code",
                    "windowsVirtualKeyCode",
                    "nativeVirtualKeyCode",
                    "modifiers",
                    "location",
                    "isKeypad",
                    "isSystemKey",
                }
            )
            mouse_up = (
                method == "Input.dispatchMouseEvent"
                and params.get("type") == "mouseReleased"
                and params.get("buttons") == 0
                and params.keys()
                <= {"type", "x", "y", "button", "buttons", "clickCount", "modifiers"}
            )
            if not (key_up or mouse_up):
                raise ControlError("browser_input_cleanup_only")
            await self._current()
            return await self.scope.page.call(method, params, timeout=timeout)
        return await self.commands.call(method, params, timeout=timeout)

    async def send(self, command: Any) -> Any:
        return await send_command(self.call, command)


class HostInput:
    """One private input page receipt per original host viewer.

    A host runs its original journal+translator INSIDE page_operation's SDK
    barrier. It must explicitly call cleanup_input before normal viewer detach
    if input may remain held. Cleanup's mandatory callback proves original
    journal custody; it is deliberately distinct from a current read grant.
    Only original key/button release commands reach the retained page socket.
    Session close invalidates receipts; it never retries uncertain cleanup.
    """

    def __init__(self, session: Any) -> None:
        self.session = session
        self.scopes: dict[str, _Scope] = {}
        self.closed = False

    def invalidate(self) -> None:
        self.closed = True
        for scope in self.scopes.values():
            scope.phase = "closed"
        self.scopes.clear()

    @staticmethod
    def _identity(viewer: str, controller: str) -> None:
        if (
            not isinstance(viewer, str)
            or not viewer
            or len(viewer) > 128
            or not isinstance(controller, str)
            or not controller
            or controller == "ai"
        ):
            raise ControlError("invalid_browser_viewer")

    async def perform(
        self,
        viewer: str,
        controller: str,
        epoch: int,
        target_epoch: int,
        operation: Callable[[_InputCommands], Awaitable[Any]],
        *,
        before_effect: Assertion,
    ) -> Any:
        self._identity(viewer, controller)
        if not callable(before_effect) or not callable(operation):
            raise ControlError("browser_authorization_required")
        if type(epoch) is not int or type(target_epoch) is not int:
            raise ControlError("stale_browser_operation")
        session = self.session

        async def run() -> Any:
            if self.closed:
                raise ControlError("browser_input_context_closed")
            page = await session._connect_page()
            await session._configure_downloads(
                controller, epoch, target_epoch, before_effect=before_effect
            )

            async def current() -> None:
                await check_effect_authorization(before_effect)
                session.control._authorize(controller, epoch, target_epoch, False)
                if self.closed or session._page is not page or page.disconnected:
                    raise ControlError("browser_input_context_closed")

            await current()
            scope = self.scopes.get(viewer)
            if scope is None:
                scope = _Scope(page, controller, session.target_id, epoch, target_epoch)
                self.scopes[viewer] = scope
            if (
                scope.phase != "ready"
                or scope.page is not page
                or scope.controller != controller
                or scope.target != session.target_id
                or (scope.epoch, scope.target_epoch) != (epoch, target_epoch)
            ):
                raise ControlError("browser_input_context_changed")
            if session._recording:
                await session._recording.prepare_input(session.target_id, page)
                await current()
            session._frame = None
            commands = _InputCommands(scope, current)
            try:
                # Host journal I/O remains in this one SDK barrier. Every
                # subsequent command checks again after that original wait.
                return await operation(commands)
            finally:
                commands.active = False

        return await session.control.run(
            controller, epoch, target_epoch, run, before_effect=before_effect
        )

    async def cleanup(
        self,
        viewer: str,
        controller: str,
        operation: Callable[[_InputCommands], Awaitable[None]],
        *,
        before_cleanup: Assertion,
    ) -> None:
        self._identity(viewer, controller)
        if not callable(before_cleanup) or not callable(operation):
            raise ControlError("browser_authorization_required")
        # Cleanup may follow grant/epoch withdrawal. It owns ONLY an original
        # private page receipt, not current pixels, coordinates or new inputs.
        async with self.session.control._operations:
            scope = self.scopes.get(viewer)
            if scope is None:
                return
            if self.closed or scope.controller != controller or scope.phase != "ready":
                raise ControlError("browser_input_context_closed")

            async def owned() -> None:
                await check_effect_authorization(before_cleanup)
                if (
                    self.closed
                    or self.scopes.get(viewer) is not scope
                    or scope.phase != "ready"
                ):
                    raise ControlError("browser_input_context_closed")

            commands = _InputCommands(scope, owned, cleanup=True)
            try:
                await owned()
                await operation(commands)
                await owned()
                scope.phase = "closed"
                self.scopes.pop(viewer)
            except BaseException:
                scope.phase = "unconfirmed"
                self.session.control.state = "error"
                self.session.control.error = "browser_input_release_uncertain"
                self.session.control.epoch += 1
                raise
            finally:
                commands.active = False
