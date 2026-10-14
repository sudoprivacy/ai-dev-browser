"""Async CDP transport extracted from Ladder's remote checkout viewer."""

import asyncio
import json
import logging

import aiohttp


class BrowserViewError(Exception):
    """A public error code, without URLs, cookies, input or protocol payloads."""

    def __init__(self, code):
        self.code = code
        self.details = None
        super().__init__(code)


class CDP:
    """Multiplex commands and events on an already authorized CDP WebSocket.

    ``error_factory`` maps generic codes to the caller's domain exception.
    This transport never starts/stops Chrome, selects a profile, authenticates
    users, or retries an input command. ``close`` disconnects only the socket.
    """

    def __init__(self, ws, on_event=None, *, error_factory=BrowserViewError):
        self.ws, self.on_event = ws, on_event
        self.error_factory = error_factory
        self.seq, self.pending = 0, {}
        self.closing = False
        self.disconnected = False
        self.reader = asyncio.create_task(self.read())

    async def read(self):
        failure = None
        try:
            async for message in self.ws:
                if message.type != aiohttp.WSMsgType.TEXT:
                    break
                value = json.loads(message.data)
                future = self.pending.pop(value.get("id"), None)
                if future and not future.done():
                    if "error" in value:
                        error = self.error_factory("operation_failed")
                        if isinstance(error, BrowserViewError):
                            # Private host diagnostics; the public message stays
                            # the generic code and never includes protocol data.
                            error.details = value["error"]
                        future.set_exception(error)
                    else:
                        future.set_result(value.get("result", {}))
                elif self.on_event and value.get("method"):
                    self.on_event(value["method"], value.get("params", {}))
        except Exception as error:  # noqa: BLE001 - Reader boundary fails every pending command.
            failure = type(error).__name__
        finally:
            self.disconnected = True
            if not self.closing:
                transport_error = self.ws.exception()
                logging.getLogger(__name__).warning(
                    "Browser view CDP closed: code=%s error=%s reader=%s",
                    self.ws.close_code,
                    type(transport_error).__name__ if transport_error else None,
                    failure,
                )
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(self.error_factory("disconnected"))
            self.pending.clear()

    async def call(self, method, params=None, timeout=20):
        if self.disconnected:
            raise self.error_factory("disconnected")
        self.seq += 1
        seq = self.seq
        future = asyncio.get_running_loop().create_future()
        self.pending[seq] = future
        try:
            await self.ws.send_json(
                {"id": seq, "method": method, "params": params or {}}
            )
            return await asyncio.wait_for(future, timeout)
        except (aiohttp.ClientError, ConnectionError) as error:
            raise self.error_factory("disconnected") from error
        finally:
            self.pending.pop(seq, None)

    async def js(self, expression):
        value = await self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        if "exceptionDetails" in value:
            raise self.error_factory("evaluation_failed")
        return value.get("result", {}).get("value")

    async def close(self):
        self.closing = True
        try:
            await self.ws.close()
        finally:
            self.reader.cancel()
            await asyncio.gather(self.reader, return_exceptions=True)
