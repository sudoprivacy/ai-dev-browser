"""Original SDK barrier/socket; journal and human authorization are fixtures."""

import asyncio
from types import SimpleNamespace

import pytest

from ai_dev_browser.remote.control import ControlError
from ai_dev_browser.remote.session import BrowserSession


async def allowed():
    return None


class Page:
    disconnected = False

    def __init__(self):
        self.calls = []
        self.fail_release = False

    async def call(self, method, params=None, timeout=20):
        self.calls.append((method, params))
        if self.fail_release and params.get("type") == "mouseReleased":
            raise ConnectionError("original release reply unavailable")
        return {}

    async def close(self):
        self.disconnected = True


async def host():
    session = BrowserSession(
        SimpleNamespace(_automation_target_id="original-target"), None
    )
    session._page = Page()
    await session.control.take("original-human")
    return session, session._page


async def packet(session, operation, *, viewer="original-viewer", current=allowed):
    return await session.page_operation(
        viewer,
        "original-human",
        session.control.epoch,
        session.control.target_epoch,
        operation,
        before_effect=current,
    )


async def cleanup(session, operation, *, viewer="original-viewer", owned=allowed):
    return await session.cleanup_input(
        viewer, "original-human", operation, before_cleanup=owned
    )


async def test_original_journal_wait_is_inside_sdk_barrier_and_rechecked_before_input():
    session, page = await host()
    entered, release = asyncio.Event(), asyncio.Event()
    grant, held = [True], []

    async def current():
        if not grant[0]:
            raise PermissionError("original human grant withdrawn")

    async def journal_then_input(commands):
        held.append("KeyA")
        entered.set()
        await release.wait()
        await commands.call(
            "Input.dispatchKeyEvent", {"type": "rawKeyDown", "code": "KeyA"}
        )

    pending = asyncio.create_task(packet(session, journal_then_input, current=current))
    await entered.wait()
    assert session.control._operations.locked() and held == ["KeyA"]
    grant[0] = False
    release.set()
    with pytest.raises(ControlError, match="^browser_authorization_denied$"):
        await pending
    assert page.calls == []

    original_journal = held

    async def owns_original():
        assert held is original_journal
        assert session.control.controller == "original-human"

    async def release_original(commands):
        await commands.call(
            "Input.dispatchKeyEvent", {"type": "keyUp", "code": held[0]}
        )
        held.clear()

    await cleanup(session, release_original, owned=owns_original)
    assert page.calls == [("Input.dispatchKeyEvent", {"type": "keyUp", "code": "KeyA"})]
    assert held == [] and session.control.controller == "original-human"
    assert session.control.state == "human" and not session._host_input.scopes


@pytest.mark.parametrize(
    "method,params",
    [
        ("Runtime.evaluate", {"expression": "private"}),
        ("Input.insertText", {"text": "private"}),
        ("Input.dispatchKeyEvent", {"type": "rawKeyDown", "key": "a"}),
        (
            "Input.dispatchKeyEvent",
            {"type": "keyUp", "key": "a", "commands": ["paste"]},
        ),
        ("Input.dispatchMouseEvent", {"type": "mousePressed", "buttons": 1}),
        ("Input.dispatchMouseEvent", {"type": "mouseReleased", "buttons": 1}),
        ("DOM.setFileInputFiles", {"files": ["private"]}),
        ("Page.navigate", {"url": "https://fixture.invalid/"}),
    ],
)
async def test_cleanup_receipt_never_authorizes_new_input_or_reads(method, params):
    session, page = await host()

    async def begin(commands):
        await commands.call(
            "Input.dispatchKeyEvent", {"type": "rawKeyDown", "key": "a"}
        )

    await packet(session, begin)
    before = list(page.calls)

    async def invalid(commands):
        await commands.call(method, params)

    with pytest.raises(ControlError, match="^browser_input_cleanup_only$"):
        await cleanup(session, invalid)
    assert page.calls == before and session.control.state == "error"
    with pytest.raises(ControlError, match="^browser_input_context_closed$"):
        await cleanup(session, invalid)
    assert page.calls == before


async def test_host_command_handle_cannot_escape_its_original_barrier():
    session, page = await host()
    handles = []

    async def capture(commands):
        handles.append(commands)

    await packet(session, capture)
    with pytest.raises(ControlError, match="^browser_input_context_closed$"):
        await handles[0].call(
            "Input.dispatchMouseEvent", {"type": "mouseReleased", "buttons": 0}
        )
    assert page.calls == []


async def test_known_release_targets_original_socket_after_selected_page_changes():
    session, original = await host()

    async def down(commands):
        await commands.call(
            "Input.dispatchMouseEvent", {"type": "mousePressed", "buttons": 1}
        )

    await packet(session, down)
    replacement = Page()
    session._page = replacement
    session.control.change_target()
    with pytest.raises(ControlError, match="^browser_input_context_changed$"):
        await packet(session, down)

    async def release(commands):
        await commands.call(
            "Input.dispatchMouseEvent", {"type": "mouseReleased", "buttons": 0}
        )

    await cleanup(session, release)
    assert len(original.calls) == 2 and replacement.calls == []
    await packet(session, down)
    assert replacement.calls == [
        ("Input.dispatchMouseEvent", {"type": "mousePressed", "buttons": 1})
    ]


async def test_control_change_during_original_journal_wait_refuses_before_native_input():
    session, page = await host()

    async def changed(commands):
        session.control.change_target()
        await commands.call("Input.insertText", {"text": "must not send"})

    with pytest.raises(ControlError, match="^stale_browser_operation$"):
        await packet(session, changed)
    assert page.calls == []


async def test_actual_cancellation_drains_original_packet_before_unlocking():
    session, page = await host()
    entered, release = asyncio.Event(), asyncio.Event()

    async def press_then_release(commands):
        await commands.call(
            "Input.dispatchKeyEvent", {"type": "rawKeyDown", "key": "a"}
        )
        entered.set()
        await release.wait()
        await commands.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": "a"})

    pending = asyncio.create_task(packet(session, press_then_release))
    await entered.wait()
    pending.cancel()
    await asyncio.sleep(0)
    assert not pending.done() and session.control._operations.locked()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert [p["type"] for _, p in page.calls] == ["rawKeyDown", "keyUp"]
    assert not session.control._operations.locked()


async def test_unknown_release_is_not_retried_on_second_cleanup_or_sdk_close():
    session, page = await host()

    async def begin(commands):
        await commands.call(
            "Input.dispatchMouseEvent", {"type": "mousePressed", "buttons": 1}
        )

    async def release(commands):
        await commands.call(
            "Input.dispatchMouseEvent", {"type": "mouseReleased", "buttons": 0}
        )

    await packet(session, begin)
    page.fail_release = True
    with pytest.raises(ConnectionError):
        await cleanup(session, release)
    assert session.control.error == "browser_input_release_uncertain"
    with pytest.raises(ControlError, match="^browser_input_context_closed$"):
        await cleanup(session, release)
    await session.close()
    assert [p["type"] for _, p in page.calls] == ["mousePressed", "mouseReleased"]
    assert page.disconnected and not session._host_input.scopes


@pytest.mark.parametrize("invalid", [None, False, "request-metadata"])
async def test_no_request_flag_can_replace_required_callback(invalid):
    session, page = await host()

    async def operation(commands):
        await commands.call("Input.insertText", {"text": "must not send"})

    with pytest.raises(ControlError, match="^browser_authorization_required$"):
        await packet(session, operation, current=invalid)
    assert page.calls == []


@pytest.mark.parametrize("value", [True, False])
async def test_truthy_or_false_callback_result_is_not_permission(value):
    session, page = await host()

    async def invalid():
        return value

    async def operation(commands):
        await commands.call("Input.insertText", {"text": "must not send"})

    with pytest.raises(ControlError, match="^invalid_browser_authorization$"):
        await packet(session, operation, current=invalid)
    assert page.calls == []


async def test_original_page_cleanup_cannot_be_borrowed_by_another_controller():
    session, page = await host()

    async def begin(commands):
        await commands.call(
            "Input.dispatchKeyEvent", {"type": "rawKeyDown", "key": "a"}
        )

    async def release(commands):
        await commands.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": "a"})

    await packet(session, begin)
    with pytest.raises(ControlError, match="^browser_input_context_closed$"):
        await session.cleanup_input(
            "original-viewer", "different-human", release, before_cleanup=allowed
        )
    assert page.calls == [
        ("Input.dispatchKeyEvent", {"type": "rawKeyDown", "key": "a"})
    ]


async def test_explicit_host_lifecycle_close_does_not_reenter_its_already_owned_barrier():
    session, page = await host()

    async def down(commands):
        await commands.call(
            "Input.dispatchKeyEvent", {"type": "rawKeyDown", "key": "a"}
        )

    await packet(session, down)
    async with asyncio.timeout(5):
        await session.control.run(
            "original-human",
            session.control.epoch,
            session.control.target_epoch,
            session.close,
            before_effect=allowed,
        )
    assert page.disconnected and not session._host_input.scopes
    assert page.calls == [
        ("Input.dispatchKeyEvent", {"type": "rawKeyDown", "key": "a"})
    ]
    assert not session.control._operations.locked()
