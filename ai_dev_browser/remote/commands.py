"""Existing checked replay forwarding shared with admitted page input."""

from collections.abc import Awaitable, Callable
from typing import Any

from .cdp import send_command

Assertion = Callable[[], Awaitable[None]]


class _Commands:
    """Typed-protocol forwarding over the SAME already selected page socket."""

    def __init__(self, page: Any, before_mutation: Assertion) -> None:
        self.page = page
        self.before_mutation = before_mutation

    async def call(
        self, method: str, params: dict[str, Any] | None = None, timeout: float = 20
    ) -> Any:
        params = params or {}
        cleanup = (
            method == "Runtime.releaseObject"
            or (
                method == "Input.dispatchMouseEvent"
                and params.get("type") == "mouseReleased"
            )
            or (method == "Input.dispatchKeyEvent" and params.get("type") == "keyUp")
        )
        if not cleanup:
            await self.before_mutation()
        return await self.page.call(method, params, timeout=timeout)

    async def send(self, command: Any) -> Any:
        return await send_command(self.call, command)
