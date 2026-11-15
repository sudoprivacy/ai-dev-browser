# Original Mosswork v1 recording data semantics: Copyright (c) 2026 OrcaKit.
# MIT terms are retained in MIT-LICENSE.txt. Execution uses this SDK's live refs.
"""Single-use checked semantic replay on one existing SDK BrowserSession.

The host supplies the original operation identity and held-principal callbacks.
No browser, authority, recording store, automatic recovery or agent is created.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import copy
from dataclasses import dataclass
import json
import math
import re
import time
from typing import Any, cast
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from ..cdp import accessibility, dom, runtime
from ..core._actionability import element_actionability
from ..core._element import Element
from ..core._ref import node_id_of
from ..core.snapshot import _format_ax_node, _get_frame_nodes, _node_attr
from ..remote.control import ControlError, check_effect_authorization
from ..remote.cdp import send_command
from ..remote.page import PageDrag, PageView
from .models import StepsDocument
from .url_filter import is_transient_auth_or_risk_url

Assertion = Callable[[], Awaitable[None]]
StepAssertions = Callable[
    [str, dict[str, Any], str, dict[str, Any] | None], Awaitable[Assertion]
]
_VARIABLE = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")
_KINDS = {
    "open",
    "navigate",
    "new_tab",
    "click",
    "fill",
    "select",
    "set_checked",
    "press",
    "scroll_to",
    "upload",
}
_VERIFICATIONS = {
    "url_contains",
    "text_contains",
    "selector_exists",
    "title_contains",
    "element_text_contains",
    "input_value_equals",
}
_KEYS = {
    "Enter",
    "Tab",
    "Escape",
    "Backspace",
    "Delete",
    "ArrowLeft",
    "ArrowRight",
    "ArrowUp",
    "ArrowDown",
    "Home",
    "End",
}


def _require(assertion: Any) -> None:
    if not callable(assertion):
        raise ControlError(
            "browser_authorization_required"
            if assertion is None
            else "invalid_browser_authorization"
        )


def _resolve(value: str, inputs: dict[str, str], *, url: bool = False) -> str:
    def substitute(match: re.Match[str]) -> str:
        key = match[1]
        if key not in inputs:
            raise ControlError("browser_replay_input_required")
        return quote(inputs[key], safe="") if url else inputs[key]

    literal = _VARIABLE.sub("", value)
    if "{{" in literal or "}}" in literal:
        raise ControlError("browser_replay_input_invalid")
    # Replacement values are data, not recursively interpreted templates.
    return _VARIABLE.sub(substitute, value)


def _url(value: str, inputs: dict[str, str]) -> str:
    result = _resolve(value, inputs, url=True)
    try:
        parsed = urlsplit(result)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError
        parsed.port
    except ValueError:
        raise ControlError("invalid_browser_url") from None
    if any(ord(char) < 32 for char in result) or len(result.encode()) > 8192:
        raise ControlError("invalid_browser_url")
    # Preserve the original recorded search-results transition using the NEW
    # query parameter, restricted to these actual search-engine domains.
    host = parsed.hostname.lower()
    key = (
        "wd"
        if host == "baidu.com" or host.endswith(".baidu.com")
        else (
            "q"
            if host in {"google.com", "www.google.com", "bing.com"}
            or host.endswith(".bing.com")
            else ""
        )
    )
    if key and inputs.get("query"):
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        if any(name == key for name, _ in pairs):
            result = urlunsplit(
                parsed._replace(
                    query=urlencode(
                        [
                            (name, inputs["query"] if name == key else item)
                            for name, item in pairs
                        ]
                    )
                )
            )
    return result


def _scroll(value: str) -> dict[str, float]:
    try:
        parts = value.split(",")
        if len(parts) != 2:
            raise ValueError
        values = [float(item) for item in parts]
        if not all(math.isfinite(item) and abs(item) <= 10000000 for item in values):
            raise ValueError
        return {"x": values[0], "y": values[1]}
    except (ValueError, TypeError, OverflowError):
        raise ControlError("invalid_browser_input") from None


def match_current_target(target: dict[str, Any], elements: list[dict[str, Any]]) -> str:
    """Match a unique current SDK reference with compatible field meaning.

    A recorded label, tag or input type constrains identity. A reused stable
    attribute cannot override conflicting semantics on the current page.
    """

    def norm(value: Any) -> str:
        return " ".join(str(value or "").split()).casefold()

    scored: dict[str, int] = {}
    name = norm(
        target.get("name")
        or target.get("label")
        or target.get("text")
        or target.get("placeholder")
    )
    for element in elements:
        ref = element.get("ref")
        if (
            not isinstance(ref, str)
            or node_id_of(ref) is None
            or element.get("disabled")
        ):
            continue
        if any(
            target.get(key) and norm(target[key]) != norm(element.get(key))
            for key in ("tag", "type")
        ) or (name and name != norm(element.get("name"))):
            continue
        score = 0
        for key, weight in (("testId", 100), ("id", 80), ("nameAttr", 60)):
            if target.get(key) and norm(target[key]) == norm(element.get(key)):
                score += weight
        if name and name == norm(element.get("name")):
            score += 50
        role = norm(target.get("role"))
        if role:
            if role != norm(element.get("role")):
                continue
            score += 25
        if score >= 50:
            scored[ref] = max(score, scored.get(ref, 0))
    if not scored:
        raise ControlError("browser_replay_target_not_found")
    best = max(scored.values())
    winners = [ref for ref, score in scored.items() if score == best]
    if len(winners) != 1:
        raise ControlError("browser_replay_target_ambiguous")
    return winners[0]


@dataclass
class _Step:
    data: dict[str, Any]
    value: str = ""
    url: str = ""


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


class CheckedReplay:
    """Use to replay reviewed semantic steps on an existing authorized session.

    Choose EventRecording for capture and page_record_start for a viewer GIF.

    Args:
        session: The host's existing BrowserSession with an acquired control lease.
        operation_id: Original durable operation identity; never replace on failure.
        actor: Authenticated owner of that lease.
        control_epoch: Current control version from that same session.
        target_epoch: Current selected-target version from that same session.
        target_bindings: Explicit recorded-to-current native target identities.
        authorize_step: Async factory taking recording ID, resolved step, current
            target and native frame facts. Returns a current async None-or-raise
            assertion for the SAME principal and full intended action/source/DLP/
            file grant. None frame means preliminary target/metadata admission.
        max_seconds: Bound for this original run, including verification waits.

    Frame facts never confer authority. The host owns durable operation admission,
    recovery, report persistence and an external atomic grant fence. Each runner
    accepts one submission; an uncertain effect must be reconciled by that host.
    """

    def __init__(
        self,
        session: Any,
        operation_id: str,
        *,
        actor: str,
        control_epoch: int,
        target_epoch: int,
        target_bindings: dict[str, str],
        authorize_step: StepAssertions,
        max_seconds: float = 300,
    ) -> None:
        _require(authorize_step)
        if not isinstance(operation_id, str) or not 1 <= len(operation_id) <= 128:
            raise ControlError("browser_replay_operation_required")
        if (
            not isinstance(actor, str)
            or not actor
            or any(type(value) is not int for value in (control_epoch, target_epoch))
        ):
            raise ControlError("invalid_browser_controller")
        if (
            not isinstance(target_bindings, dict)
            or len(target_bindings) > 128
            or any(
                not isinstance(key, str)
                or not key
                or not isinstance(value, str)
                or not value
                for key, value in target_bindings.items()
            )
        ):
            raise ControlError("browser_replay_target_binding_required")
        if (
            type(max_seconds) not in (int, float)
            or not math.isfinite(max_seconds)
            or not 0 < max_seconds <= 1800
        ):
            raise ValueError("Bounded replay duration required")
        self.session, self.operation_id, self.actor = session, operation_id, actor
        self.epoch, self.target_epoch = control_epoch, target_epoch
        self.bindings = dict(target_bindings)
        self.authorize = authorize_step
        self.max_seconds = max_seconds
        self._used = False
        self._sent = False
        self._any_effect = False
        self._deadline = 0.0
        self._report: dict[str, Any] = {
            "operationId": operation_id,
            "status": "not_started",
            "steps": [],
            "verification": [],
        }

    def status(self) -> dict[str, Any]:
        """Host-only outcome metadata, with no inputs/DOM/URL/secret values."""
        return copy.deepcopy(self._report)

    def _plan(
        self, document: StepsDocument | dict[str, Any], inputs: dict[str, str]
    ) -> tuple[StepsDocument, list[_Step]]:
        raw = (
            document.model_dump(by_alias=True)
            if isinstance(document, StepsDocument)
            else copy.deepcopy(document)
        )
        try:
            if len(json.dumps(raw, allow_nan=False).encode()) > 4 * 1024 * 1024:
                raise ValueError
            doc = StepsDocument.model_validate(raw, strict=True)
        except Exception:
            raise ControlError("browser_replay_document_invalid") from None
        if (
            doc.schema_version != "1.0"
            or not doc.recording_id
            or not 1 <= len(doc.steps) <= 10000
        ):
            raise ControlError("browser_replay_document_invalid")
        if not isinstance(inputs, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) or len(v.encode()) > 8192
            for k, v in inputs.items()
        ):
            raise ControlError("browser_replay_input_invalid")
        declared = [item.get("name") for item in doc.inputs]
        if any(not isinstance(name, str) or not name for name in declared) or len(
            set(declared)
        ) != len(declared):
            raise ControlError("browser_replay_input_invalid")
        if set(inputs) - set(declared):
            raise ControlError("browser_replay_input_invalid")
        if any(
            item.get("required") is not False and item["name"] not in inputs
            for item in doc.inputs
        ):
            raise ControlError("browser_replay_input_required")
        ids = set()
        steps = []
        for item in doc.steps:
            if not item.id or item.id in ids or item.kind not in _KINDS:
                raise ControlError("browser_replay_step_invalid")
            ids.add(item.id)
            value = _resolve(item.value or "", inputs)
            url = (
                _url(item.url, inputs)
                if item.kind in {"open", "navigate", "new_tab"} and item.url
                else ""
            )
            if item.kind in {"open", "navigate", "new_tab"} and not url:
                raise ControlError("invalid_browser_url")
            if (
                item.kind in {"click", "fill", "select", "set_checked", "upload"}
                and not item.target
            ):
                raise ControlError("browser_replay_target_not_found")
            if item.kind == "set_checked" and value not in {"true", "false"}:
                raise ControlError("browser_replay_input_invalid")
            if item.kind == "press" and item.key not in _KEYS:
                raise ControlError("invalid_browser_input")
            if item.kind == "scroll_to":
                _scroll(value)
            if item.kind == "upload":
                try:
                    files = json.loads(value)
                    if (
                        not isinstance(files, list)
                        or not 1 <= len(files) <= 20
                        or any(
                            not isinstance(f, str)
                            or re.fullmatch(r"[0-9a-f]{32}", f) is None
                            for f in files
                        )
                        or len(set(files)) != len(files)
                    ):
                        raise ValueError
                except (ValueError, TypeError):
                    raise ControlError("browser_files_invalid_selection") from None
            if item.expect and (
                set(item.expect) - {"urlAfter", "urlContains"}
                or any(not isinstance(v, str) or not v for v in item.expect.values())
            ):
                raise ControlError("browser_replay_verification_invalid")
            steps.append(_Step(item.model_dump(), value, url))
        for verification in doc.verification:
            if verification.get("type") not in _VERIFICATIONS:
                raise ControlError("browser_replay_verification_invalid")
            if not isinstance(verification.get("value"), str) or (
                verification["type"] != "input_value_equals"
                and not verification["value"]
            ):
                raise ControlError("browser_replay_verification_invalid")
            if verification["type"] in {
                "selector_exists",
                "element_text_contains",
                "input_value_equals",
            } and not isinstance(
                verification.get(
                    "selector",
                    verification.get("value")
                    if verification["type"] == "selector_exists"
                    else None,
                ),
                str,
            ):
                raise ControlError("browser_replay_verification_invalid")
        return doc, steps

    async def _assertion(
        self, recording: str, step: _Step, target: str, frame: dict[str, Any] | None
    ) -> Assertion:
        try:
            request = {
                **copy.deepcopy(step.data),
                "value": step.value,
                "url": step.url or step.data.get("url"),
            }
            assertion = await self.authorize(
                recording, request, target, copy.deepcopy(frame)
            )
        except PermissionError:
            raise ControlError("browser_authorization_denied") from None
        except Exception:
            raise ControlError("browser_authorization_unavailable") from None
        _require(assertion)
        await check_effect_authorization(assertion)
        return assertion

    async def _frame(self, page: Any, target: dict[str, Any]) -> dict[str, Any]:
        tree = await page.call("Page.getFrameTree")
        frames: list[dict[str, Any]] = []

        def visit(node: dict[str, Any], lineage: list[str]) -> None:
            frame = node["frame"]
            origin = frame.get("securityOrigin")
            if not isinstance(origin, str):
                raise ControlError("browser_replay_frame_invalid")
            current = {
                "id": frame["id"],
                "loaderId": frame.get("loaderId"),
                "url": frame["url"],
                "origin": origin,
                "path": lineage,
            }
            frames.append(current)
            if len(frames) > 128 or len(lineage) > 16:
                raise ControlError("browser_replay_frame_invalid")
            for child in node.get("childFrames", []):
                child_origin = child["frame"].get("securityOrigin")
                if not isinstance(child_origin, str):
                    raise ControlError("browser_replay_frame_invalid")
                visit(child, [*lineage, child_origin])

        visit(tree["frameTree"], [])
        path = target.get("framePath", [])
        if not isinstance(path, list) or any(
            not isinstance(value, str) for value in path
        ):
            raise ControlError("browser_replay_frame_invalid")
        matches = [frame for frame in frames if frame["path"] == path]
        if len(matches) != 1:
            raise ControlError("browser_replay_frame_ambiguous")
        return matches[0]

    async def _perform(self, recording: str, step: _Step, assertion: Assertion) -> None:
        session = self.session
        page = await session._connect_page()
        target_id = session.target_id
        frame = await self._frame(page, step.data.get("target") or {})
        current = await self._assertion(recording, step, target_id, frame)
        focused: Element | None = None
        pointer: dict[str, float] | None = None
        element: Any = None
        selected_backend: int | None = None

        async def check_target() -> None:
            session.control._authorize(self.actor, self.epoch, self.target_epoch, False)
            if (
                session.target_id != target_id
                or session._page is not page
                or page.disconnected
            ):
                raise ControlError("stale_browser_operation")
            fresh = await self._frame(page, step.data.get("target") or {})
            if fresh != frame:
                raise ControlError("browser_replay_document_changed")
            if selected_backend is not None:
                await self._check_selected_target(
                    page, frame, step.data["target"], selected_backend
                )
            if (
                focused is not None
                and await focused.apply(
                    "el=>el.ownerDocument.hasFocus()&&el.ownerDocument.activeElement===el"
                )
                is not True
            ):
                raise ControlError("browser_replay_focus_changed")
            if pointer is not None:
                actual = await cast(Any, element_actionability)(element)
                if (
                    not isinstance(actual, dict)
                    or not actual.get("actionable")
                    or actual.get("point") != pointer
                ):
                    raise ControlError("browser_replay_target_changed")
            session.control._authorize(self.actor, self.epoch, self.target_epoch, False)

        async def check() -> None:
            await check_effect_authorization(assertion)
            await check_effect_authorization(current)
            await check_target()

        async def mutating() -> None:
            if time.monotonic() >= self._deadline:
                raise ControlError("browser_replay_deadline")
            await check()
            # Authority callbacks may themselves yield while the site changes
            # document or keyboard focus. Check that exact native target again
            # before dispatch; the host still owns an atomic external grant fence.
            await check_effect_authorization(current)
            await check_target()
            self._sent = True
            self._any_effect = True

        commands = _Commands(page, mutating)
        await check()
        kind = step.data["kind"]
        try:
            if kind in {"open", "navigate"}:
                await mutating()
                result = await page.call("Page.navigate", {"url": step.url})
                if result.get("errorText"):
                    raise ControlError("browser_replay_navigation_failed")
                await page.wait_navigation(result)
            elif kind == "scroll_to":
                value = _scroll(step.value)
                await mutating()
                result = await page.call(
                    "Runtime.evaluate",
                    {
                        "expression": "window.scrollTo("
                        + json.dumps(value["x"])
                        + ","
                        + json.dumps(value["y"])
                        + ")",
                        "returnByValue": True,
                    },
                )
                if result.get("exceptionDetails"):
                    raise ControlError("browser_replay_action_failed")
            elif kind == "press" and not any(
                (step.data.get("target") or {}).get(key)
                for key in ("name", "id", "role", "testId", "nameAttr")
            ):
                width, height = await session._dimensions(page)
                if not await cast(Any, PageView)().input(
                    commands,
                    {"kind": "key", "key": step.data["key"]},
                    width=width,
                    height=height,
                    dialog=session._dialog,
                ):
                    raise ControlError("invalid_browser_input")
            else:
                # Existing SDK AX decoder/formatter/ref grammar, on this exact
                # connection. No stale recorded ref, bounding box or eval code.
                nodes = await self._nodes(page, frame)
                ref = match_current_target(step.data["target"], nodes)
                backend = node_id_of(ref)
                assert backend is not None
                selected_backend = backend
                element = await Element.from_backend_node(cast(Any, page), backend)
                state = await cast(Any, element_actionability)(element)
                if not isinstance(state, dict) or not state.get("actionable"):
                    raise ControlError("browser_replay_target_unavailable")
                if kind in {"click", "set_checked"}:
                    pointer = state["point"]
                await check()
                if kind in {"click", "set_checked"}:
                    selected = next(node for node in nodes if node["ref"] == ref)
                    checked = selected.get("checked")
                    desired = step.value == "true"
                    if kind == "set_checked" and checked not in {
                        True,
                        False,
                        "true",
                        "false",
                    }:
                        raise ControlError("browser_replay_checkbox_invalid")
                    if kind == "click" or (checked in {True, "true"}) != desired:
                        width, height = await session._dimensions(page)
                        drag = cast(Any, PageDrag)(commands, width, height)
                        try:
                            await drag.press(state["point"])
                        finally:
                            await drag.release()
                elif kind in {"fill", "press"}:
                    await commands.send(
                        dom.focus(backend_node_id=dom.BackendNodeId(backend))
                    )
                    width, height = await session._dimensions(page)
                    focused = element
                    view = cast(Any, PageView)(max_text=8192)
                    events = (
                        ({"kind": "key", "key": step.data["key"]},)
                        if kind == "press"
                        else (
                            {"kind": "key", "key": "SelectAll"},
                            {"kind": "paste", "text": step.value}
                            if step.value
                            else {"kind": "key", "key": "Backspace"},
                        )
                    )
                    for event in events:
                        if not await view.input(
                            commands,
                            event,
                            width=width,
                            height=height,
                            dialog=session._dialog,
                        ):
                            raise ControlError("invalid_browser_input")
                    focused = None
                elif kind == "select":
                    await element._resolve()
                    function = "function(value){if(this.tagName!=='SELECT'||this.multiple||![...this.options].some(o=>o.value===value&&!o.disabled))throw Error('unavailable');this.value=value;this.dispatchEvent(new Event('input',{bubbles:true}));this.dispatchEvent(new Event('change',{bubbles:true}));return this.value===value;}"
                    result, error = await commands.send(
                        runtime.call_function_on(
                            function,
                            object_id=element.object_id,
                            arguments=[runtime.CallArgument(value=step.value)],
                            return_by_value=True,
                            user_gesture=True,
                        )
                    )
                    if error or result.value is not True:
                        raise ControlError("browser_replay_action_failed")
                elif kind == "upload":
                    file_ids = json.loads(step.value)
                    if (
                        not session.files
                        or not isinstance(file_ids, list)
                        or not 1 <= len(file_ids) <= 20
                        or any(not isinstance(item, str) for item in file_ids)
                        or len(set(file_ids)) != len(file_ids)
                    ):
                        raise ControlError("browser_files_invalid_selection")
                    paths = [
                        str(
                            await asyncio.to_thread(
                                session.files.browser_path, item, kind="upload"
                            )
                        )
                        for item in file_ids
                    ]
                    await commands.send(
                        dom.set_file_input_files(
                            paths, backend_node_id=dom.BackendNodeId(backend)
                        )
                    )
                    actual = await element.apply(
                        "el=>Array.from(el.files||[]).map(f=>({name:f.name,bytes:f.size}))"
                    )
                    expected = [
                        {
                            key: session.files.metadata(item)[key]
                            for key in ("name", "bytes")
                        }
                        for item in file_ids
                    ]
                    if actual != expected:
                        raise ControlError("browser_replay_file_unconfirmed")
            await check_effect_authorization(current)
            session.control._authorize(self.actor, self.epoch, self.target_epoch, False)
            actual_frame = await self._frame(page, step.data.get("target") or {})
            if actual_frame != frame:
                if kind not in {"open", "navigate"} and not step.data.get("expect"):
                    raise ControlError("browser_replay_document_changed")
                await self._assertion(recording, step, target_id, actual_frame)
            if kind == "set_checked":
                nodes = await self._nodes(page, actual_frame)
                current_ref = match_current_target(step.data["target"], nodes)
                state = next(node for node in nodes if node["ref"] == current_ref).get(
                    "checked"
                )
                if state not in {True, False, "true", "false"} or (
                    state in {True, "true"}
                ) != (step.value == "true"):
                    raise ControlError("browser_replay_checkbox_unconfirmed")
        finally:
            if element is not None:
                try:
                    await element.release()
                except Exception:
                    pass  # A retired JS handle does not authorize input replay.

    async def _nodes(self, page: Any, frame: dict[str, Any]) -> list[dict[str, Any]]:
        nodes = await cast(Any, _get_frame_nodes)(page, frame["id"], True, 10)
        if not isinstance(nodes, list) or len(nodes) > 2000:
            raise ControlError("browser_replay_target_limit")
        for node in nodes:
            await self._describe_node(page, node)
        return cast(list[dict[str, Any]], nodes)

    async def _describe_node(self, page: Any, node: dict[str, Any]) -> None:
        backend = node_id_of(node["ref"])
        if backend is None:
            return
        native = await page.send(
            dom.describe_node(backend_node_id=dom.BackendNodeId(backend), depth=0)
        )
        tag = str(getattr(native, "node_name", "") or "").lower()
        node.update(
            id=_node_attr(native, "id"),
            nameAttr=_node_attr(native, "name"),
            testId=_node_attr(native, "data-testid")
            or _node_attr(native, "data-test")
            or _node_attr(native, "data-cy"),
            tag=tag,
            type=_node_attr(native, "type") or ("text" if tag == "input" else ""),
        )

    async def _check_selected_target(
        self, page: Any, frame: dict[str, Any], target: dict[str, Any], backend: int
    ) -> None:
        # Reuse the core AX formatter and matcher on this one native node. A
        # current authority callback can yield while labels or input types
        # change; a live backend ID alone does not preserve field meaning.
        native_nodes = await page.send(
            accessibility.get_partial_ax_tree(
                backend_node_id=dom.BackendNodeId(backend), fetch_relatives=False
            )
        )
        candidates = []
        for native in native_nodes:
            if getattr(native, "backend_dom_node_id", None) == backend:
                candidates.extend(cast(Any, _format_ax_node)(native, [0], 0))
        if not candidates:
            # Preserve the existing core's ARIA-less DOM discovery fallback.
            candidates = [
                node
                for node in await self._nodes(page, frame)
                if node_id_of(node["ref"]) == backend
            ]
        else:
            for candidate in candidates:
                await self._describe_node(page, candidate)
        try:
            ref = match_current_target(target, candidates)
        except ControlError:
            raise ControlError("browser_replay_target_changed") from None
        if node_id_of(ref) != backend:
            raise ControlError("browser_replay_target_changed")

    async def _verify(
        self, recording: str, specification: dict[str, Any], inputs: dict[str, str]
    ) -> None:
        typ = specification["type"]
        value = _resolve(specification["value"], inputs)
        selector = specification.get(
            "selector", value if typ == "selector_exists" else ""
        )
        spec = {**copy.deepcopy(specification), "value": value}
        step = _Step({"id": "verification", "kind": "verify", **spec}, value)
        target = self.session.target_id
        initial = await self._assertion(recording, step, target, None)
        deadline = min(self._deadline, time.monotonic() + 10)

        async def observe() -> None:
            page = await self.session._connect_page()
            while True:
                await check_effect_authorization(initial)
                frame = await self._frame(page, {})
                current = await self._assertion(recording, step, target, frame)
                if typ == "url_contains":
                    passed = value in frame["url"]
                elif typ == "url_equals":
                    passed = value == frame["url"]
                else:
                    literal, query = json.dumps(value), json.dumps(selector)
                    expressions = {
                        "title_contains": "document.title.includes(" + literal + ")",
                        "text_contains": "(document.body?.innerText||'').includes("
                        + literal
                        + ")",
                        "selector_exists": "!!document.querySelector(" + query + ")",
                        "element_text_contains": "(()=>{const e=document.querySelector("
                        + query
                        + ");return !!e&&(e.innerText||e.textContent||'').includes("
                        + literal
                        + ");})()",
                        "input_value_equals": "(()=>{const e=document.querySelector("
                        + query
                        + ");return !!e&&String(e.value??'')==="
                        + literal
                        + ";})()",
                    }
                    if typ not in expressions:
                        raise ControlError("browser_replay_verification_invalid")
                    passed = await page.js(expressions[typ]) is True
                await check_effect_authorization(current)
                self.session.control._authorize(
                    self.actor, self.epoch, self.target_epoch, True
                )
                if self.session._page is not page or self.session.target_id != target:
                    raise ControlError("browser_replay_document_changed")
                fresh = await self._frame(page, {})
                self.session.control._authorize(
                    self.actor, self.epoch, self.target_epoch, True
                )
                if time.monotonic() >= deadline:
                    raise ControlError("browser_replay_verification_failed")
                if fresh != frame:
                    # Navigation can commit during the current assertion/read.
                    # Discard this observation and admit the next native document
                    # on the next iteration. Never replay the preceding effect.
                    await asyncio.sleep(0.05)
                    continue
                if passed:
                    return
                await asyncio.sleep(0.05)

        await self.session.control.run(
            self.actor,
            self.epoch,
            self.target_epoch,
            observe,
            observation=True,
            before_effect=initial,
        )

    async def run(
        self,
        document: StepsDocument | dict[str, Any],
        inputs: dict[str, str],
        *,
        before_run: Assertion,
        before_result: Assertion,
    ) -> dict[str, Any]:
        """Submit this original operation once; returns metadata without input values.

        Args:
            document: Reviewed StepsDocument or its JSON-compatible dictionary.
            inputs: Explicit current values for declared variables; never defaults.
            before_run: Current assertion admitting the original durable operation.
            before_result: Current assertion permitting release of its report.

        Raises:
            ControlError: Invalid, ambiguous, changed or unauthorized work is
                refused. A possible effect reports browser_replay_write_unconfirmed;
                inspect status() and reconcile before any further submission.
            asyncio.CancelledError: Cancellation after the original control barrier
                drains. The report preserves possible-effect metadata.
        """
        _require(before_run)
        _require(before_result)
        if self._used:
            raise ControlError("browser_replay_already_submitted")
        self._used = True
        deadline = time.monotonic() + self.max_seconds
        self._deadline = deadline
        try:
            doc, steps = self._plan(document, copy.deepcopy(inputs))
            await check_effect_authorization(before_run)
            self._report.update(recordingId=doc.recording_id, status="running")
            for step in steps:
                self._sent = False
                entry = {
                    "id": step.data["id"],
                    "kind": step.data["kind"],
                    "status": "running",
                }
                self._report["steps"].append(entry)
                if time.monotonic() >= deadline:
                    raise ControlError("browser_replay_deadline")
                recorded = (step.data.get("target") or {}).get("targetId", "")
                mapped = (
                    self.bindings.get(recorded) if recorded else self.session.target_id
                )
                if recorded and mapped is None and step.data["kind"] != "new_tab":
                    raise ControlError("browser_replay_target_binding_required")
                target = mapped or self.session.target_id
                assertion = await self._assertion(doc.recording_id, step, target, None)
                if step.data["kind"] == "navigate" and is_transient_auth_or_risk_url(
                    step.url
                ):
                    entry.update(
                        status="skipped", reason="transient_auth_or_risk_redirect"
                    )
                    continue
                if step.data["kind"] == "new_tab" or target != self.session.target_id:
                    action = (
                        {"kind": "new-tab"}
                        if step.data["kind"] == "new_tab"
                        else {"kind": "select-tab", "targetId": target}
                    )
                    # Lifecycle can commit before transport/post-check failure;
                    # retain this original operation, never create a retry tab.
                    self._sent = True
                    self._any_effect = True
                    await self.session.action(
                        self.actor,
                        self.epoch,
                        self.target_epoch,
                        action,
                        before_effect=assertion,
                    )
                    self.target_epoch = self.session.control.target_epoch
                    if recorded:
                        self.bindings[recorded] = self.session.target_id
                    if step.data["kind"] == "new_tab":
                        step.data["kind"] = "open"
                    assertion = await self._assertion(
                        doc.recording_id, step, self.session.target_id, None
                    )

                async def perform() -> None:
                    await self._perform(doc.recording_id, step, assertion)

                await self.session.control.run(
                    self.actor,
                    self.epoch,
                    self.target_epoch,
                    perform,
                    before_effect=assertion,
                )
                entry["status"] = "passed"
                if step.data.get("expect"):
                    expect = step.data["expect"]
                    if expect.get("urlAfter"):
                        await self._verify(
                            doc.recording_id,
                            {
                                "type": "url_equals",
                                "value": _url(expect["urlAfter"], inputs),
                            },
                            inputs,
                        )
                    if expect.get("urlContains"):
                        await self._verify(
                            doc.recording_id,
                            {"type": "url_contains", "value": expect["urlContains"]},
                            inputs,
                        )
            for verification in doc.verification:
                entry = {"type": verification["type"], "status": "running"}
                self._report["verification"].append(entry)
                await self._verify(doc.recording_id, verification, inputs)
                entry["status"] = "passed"
            self._sent = self._any_effect
            await check_effect_authorization(before_result)
            self._report["status"] = "passed"
            return self.status()
        except asyncio.CancelledError:
            self._report["status"] = "cancelled"
            self._report["possibleEffect"] = self._any_effect
            raise
        except Exception as error:
            code = (
                error.code
                if isinstance(error, ControlError)
                else "browser_replay_unavailable"
            )
            self._report.update(
                status="unconfirmed" if self._sent else "failed", error=code
            )
            if (
                self._report["steps"]
                and self._report["steps"][-1]["status"] == "running"
            ):
                self._report["steps"][-1]["status"] = self._report["status"]
            raise ControlError(
                "browser_replay_write_unconfirmed" if self._sent else code
            ) from None
