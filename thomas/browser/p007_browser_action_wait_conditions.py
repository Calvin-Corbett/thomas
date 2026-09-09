"""
P007 - Browser action wait conditions

This module implements a Thomas-native contract for expressing explicit
"wait conditions" that must be satisfied *after* a browser action runs.

Key goals:
- Strict, machine-friendly input contracts (JSON -> dataclasses).
- Deterministic error codes/messages for invalid input and browser failures.
- Works with any "page" object exposing Playwright-like methods.

The page object is expected to support some subset of:
- goto(url)
- click(selector)
- fill(selector, text)
- type(selector, text)
- press(selector, key)
- select_option(selector, value)
- wait_for_selector(selector, state=?, timeout=?)
- wait_for_load_state(state, timeout=?)
- wait_for_url(url, timeout=?)
- wait_for_timeout(ms)

If a required method is missing, a deterministic BROWSER_FAILURE error is raised.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Union, cast

# ----------------------------
# Public types / contracts
# ----------------------------

WaitKind = Literal["selector", "load_state", "url", "timeout"]
SelectorState = Literal["attached", "detached", "visible", "hidden"]
LoadState = Literal["load", "domcontentloaded", "networkidle"]

ActionKind = Literal["click", "goto", "fill", "press", "type", "select"]


@dataclass(frozen=True)
class ErrorInfo:
    """Machine-readable error information."""

    code: str
    message: str


class WaitConditionsError(Exception):
    """Base error for wait-condition handling with deterministic fields."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def to_error_info(self) -> ErrorInfo:
        return ErrorInfo(code=self.code, message=self.message)


class InvalidWaitConditionsError(WaitConditionsError):
    """Raised for invalid user input/spec."""

    def __init__(self, message: str):
        super().__init__(code="INVALID_INPUT", message=message)


class BrowserWaitFailureError(WaitConditionsError):
    """Raised when the underlying browser/page fails during action or waiting."""

    def __init__(self, message: str):
        super().__init__(code="BROWSER_FAILURE", message=message)


class MissingBrowserDriverError(WaitConditionsError):
    """Raised when execution requires a browser driver that is unavailable."""

    def __init__(self, message: str):
        super().__init__(code="MISSING_BROWSER", message=message)


@dataclass(frozen=True)
class WaitForSelector:
    kind: Literal["selector"]
    selector: str
    state: SelectorState = "visible"
    timeout_ms: int | None = None


@dataclass(frozen=True)
class WaitForLoadState:
    kind: Literal["load_state"]
    state: LoadState = "load"
    timeout_ms: int | None = None


@dataclass(frozen=True)
class WaitForURL:
    kind: Literal["url"]
    url: str
    timeout_ms: int | None = None


@dataclass(frozen=True)
class WaitTimeout:
    kind: Literal["timeout"]
    timeout_ms: int


WaitCondition = Union[WaitForSelector, WaitForLoadState, WaitForURL, WaitTimeout]


@dataclass(frozen=True)
class BrowserAction:
    kind: ActionKind
    selector: str | None = None
    url: str | None = None
    text: str | None = None
    key: str | None = None


@dataclass(frozen=True)
class ActionWithWaits:
    """
    Input contract for action + waits.

    default_timeout_ms applies to waits that omit their own timeout_ms.
    """

    action: BrowserAction
    waits: tuple[WaitCondition, ...] = ()
    default_timeout_ms: int | None = None


@dataclass(frozen=True)
class PlannedCall:
    """A planned page method call (useful for dry-run / automation)."""

    method: str
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionWaitPlan:
    action_call: PlannedCall
    wait_calls: tuple[PlannedCall, ...]


# ----------------------------
# Parsing helpers
# ----------------------------

_ALLOWED_SPEC_KEYS = {"action", "waits", "default_timeout_ms"}
_ALLOWED_ACTION_KEYS = {"kind", "selector", "url", "text", "key"}
_ALLOWED_WAIT_KEYS = {"kind", "selector", "state", "url", "timeout_ms"}


def _validate_allowed_keys(obj: Mapping[str, Any], allowed: set[str], *, ctx: str) -> None:
    extra = set(obj.keys()) - allowed
    if extra:
        # Deterministic ordering for error message
        extras = ", ".join(sorted(extra))
        raise InvalidWaitConditionsError(f"{ctx} has unexpected field(s): {extras}")


def _coerce_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        # bool is an int subclass; treat as invalid for this use-case.
        raise InvalidWaitConditionsError(f"{field} must be an integer (ms), got bool")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        s = value.strip()
        if s.isdigit():
            return int(s)
    raise InvalidWaitConditionsError(f"{field} must be an integer (ms)")


def _coerce_timeout_ms_optional(value: Any, *, field: str) -> int | None:
    if value is None:
        return None
    v = _coerce_int(value, field=field)
    if v < 0:
        raise InvalidWaitConditionsError(f"{field} must be >= 0")
    return v


def _coerce_timeout_ms_required(value: Any, *, field: str) -> int:
    if value is None:
        raise InvalidWaitConditionsError(f"{field} is required")
    v = _coerce_int(value, field=field)
    if v < 0:
        raise InvalidWaitConditionsError(f"{field} must be >= 0")
    return v


def _require_str(value: Any, *, field: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    raise InvalidWaitConditionsError(f"{field} must be a non-empty string")


def parse_wait_conditions(raw: Any) -> tuple[WaitCondition, ...]:
    """
    Parse wait conditions from a Python structure (already-decoded JSON).

    Expected format: a list of objects, each with a 'kind' field.

    Supported kinds:
      - selector: {kind, selector, state?, timeout_ms?}
      - load_state: {kind, state?, timeout_ms?}
      - url: {kind, url, timeout_ms?}
      - timeout: {kind, timeout_ms}
    """
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise InvalidWaitConditionsError("waits must be a list")

    waits: list[WaitCondition] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise InvalidWaitConditionsError(f"waits[{idx}] must be an object")
        _validate_allowed_keys(item, _ALLOWED_WAIT_KEYS, ctx=f"waits[{idx}]")

        kind = item.get("kind")
        if kind not in ("selector", "load_state", "url", "timeout"):
            raise InvalidWaitConditionsError(f"waits[{idx}].kind must be one of selector|load_state|url|timeout")

        if kind == "selector":
            selector = _require_str(item.get("selector"), field=f"waits[{idx}].selector")
            state_raw = item.get("state", "visible")
            if state_raw not in ("attached", "detached", "visible", "hidden"):
                raise InvalidWaitConditionsError(f"waits[{idx}].state must be one of attached|detached|visible|hidden")
            timeout_val = _coerce_timeout_ms_optional(item.get("timeout_ms"), field=f"waits[{idx}].timeout_ms")
            waits.append(
                WaitForSelector(
                    kind="selector",
                    selector=selector,
                    state=cast(SelectorState, state_raw),
                    timeout_ms=timeout_val,
                )
            )
            continue

        if kind == "load_state":
            state_raw = item.get("state", "load")
            if state_raw not in ("load", "domcontentloaded", "networkidle"):
                raise InvalidWaitConditionsError(f"waits[{idx}].state must be one of load|domcontentloaded|networkidle")
            timeout_val = _coerce_timeout_ms_optional(item.get("timeout_ms"), field=f"waits[{idx}].timeout_ms")
            waits.append(WaitForLoadState(kind="load_state", state=cast(LoadState, state_raw), timeout_ms=timeout_val))
            continue

        if kind == "url":
            url = _require_str(item.get("url"), field=f"waits[{idx}].url")
            timeout_val = _coerce_timeout_ms_optional(item.get("timeout_ms"), field=f"waits[{idx}].timeout_ms")
            waits.append(WaitForURL(kind="url", url=url, timeout_ms=timeout_val))
            continue

        if kind == "timeout":
            timeout_val = _coerce_timeout_ms_required(item.get("timeout_ms"), field=f"waits[{idx}].timeout_ms")
            waits.append(WaitTimeout(kind="timeout", timeout_ms=timeout_val))
            continue

        # Defensive (should be unreachable).
        raise InvalidWaitConditionsError(f"waits[{idx}].kind is unsupported")

    return tuple(waits)


def parse_action(raw: Any) -> BrowserAction:
    """
    Parse an action object.

    Supported kinds:
      - goto: {kind, url}
      - click: {kind, selector}
      - fill: {kind, selector, text}
      - press: {kind, selector, key}
      - type: {kind, selector, text}
      - select: {kind, selector, text}
    """
    if not isinstance(raw, Mapping):
        raise InvalidWaitConditionsError("action must be an object")
    _validate_allowed_keys(raw, _ALLOWED_ACTION_KEYS, ctx="action")

    kind = raw.get("kind")
    if kind not in ("goto", "click", "fill", "press", "type", "select"):
        raise InvalidWaitConditionsError("action.kind must be one of goto|click|fill|press|type|select")

    if kind == "goto":
        url = _require_str(raw.get("url"), field="action.url")
        return BrowserAction(kind="goto", url=url)

    selector = _require_str(raw.get("selector"), field="action.selector")

    if kind == "click":
        return BrowserAction(kind="click", selector=selector)

    if kind in ("fill", "type", "select"):
        text = _require_str(raw.get("text"), field="action.text")
        return BrowserAction(kind=cast(ActionKind, kind), selector=selector, text=text)

    if kind == "press":
        key = _require_str(raw.get("key"), field="action.key")
        return BrowserAction(kind="press", selector=selector, key=key)

    # Defensive (should be unreachable).
    raise InvalidWaitConditionsError("Unsupported action.kind")


def parse_action_with_waits(raw: Any) -> ActionWithWaits:
    """
    Parse full spec: {action: {...}, waits?: [...], default_timeout_ms?: int}
    """
    if not isinstance(raw, Mapping):
        raise InvalidWaitConditionsError("spec must be an object")
    _validate_allowed_keys(raw, _ALLOWED_SPEC_KEYS, ctx="spec")

    if "action" not in raw:
        raise InvalidWaitConditionsError("spec.action is required")

    action = parse_action(raw.get("action"))
    waits = parse_wait_conditions(raw.get("waits", None))
    default_timeout_val = _coerce_timeout_ms_optional(raw.get("default_timeout_ms"), field="spec.default_timeout_ms")

    return ActionWithWaits(action=action, waits=waits, default_timeout_ms=default_timeout_val)


# ----------------------------
# Planning
# ----------------------------


def plan_wait_calls(
    waits: Sequence[WaitCondition],
    *,
    default_timeout_ms: int | None = None,
) -> tuple[PlannedCall, ...]:
    calls: list[PlannedCall] = []
    for w in waits:
        if isinstance(w, WaitForSelector):
            timeout = w.timeout_ms if w.timeout_ms is not None else default_timeout_ms
            kwargs: dict[str, Any] = {"state": w.state}
            if timeout is not None:
                kwargs["timeout"] = timeout
            calls.append(PlannedCall(method="wait_for_selector", args=(w.selector,), kwargs=kwargs))
            continue

        if isinstance(w, WaitForLoadState):
            timeout = w.timeout_ms if w.timeout_ms is not None else default_timeout_ms
            kwargs = {}
            if timeout is not None:
                kwargs["timeout"] = timeout
            calls.append(PlannedCall(method="wait_for_load_state", args=(w.state,), kwargs=kwargs))
            continue

        if isinstance(w, WaitForURL):
            timeout = w.timeout_ms if w.timeout_ms is not None else default_timeout_ms
            kwargs = {}
            if timeout is not None:
                kwargs["timeout"] = timeout
            calls.append(PlannedCall(method="wait_for_url", args=(w.url,), kwargs=kwargs))
            continue

        if isinstance(w, WaitTimeout):
            calls.append(PlannedCall(method="wait_for_timeout", args=(w.timeout_ms,), kwargs={}))
            continue

        raise InvalidWaitConditionsError("Unknown wait condition type")

    return tuple(calls)


def plan_action_with_waits(spec: ActionWithWaits) -> ActionWaitPlan:
    a = spec.action
    if a.kind == "goto":
        action_call = PlannedCall(method="goto", args=(cast(str, a.url),), kwargs={})
    elif a.kind == "click":
        action_call = PlannedCall(method="click", args=(cast(str, a.selector),), kwargs={})
    elif a.kind == "fill":
        action_call = PlannedCall(method="fill", args=(cast(str, a.selector), cast(str, a.text)), kwargs={})
    elif a.kind == "type":
        action_call = PlannedCall(method="type", args=(cast(str, a.selector), cast(str, a.text)), kwargs={})
    elif a.kind == "select":
        # Best-effort mapping to Playwright's `select_option`.
        action_call = PlannedCall(method="select_option", args=(cast(str, a.selector), cast(str, a.text)), kwargs={})
    elif a.kind == "press":
        action_call = PlannedCall(method="press", args=(cast(str, a.selector), cast(str, a.key)), kwargs={})
    else:
        raise InvalidWaitConditionsError("Unsupported action.kind")

    wait_calls = plan_wait_calls(spec.waits, default_timeout_ms=spec.default_timeout_ms)
    return ActionWaitPlan(action_call=action_call, wait_calls=wait_calls)


# ----------------------------
# Execution
# ----------------------------


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value) or asyncio.isfuture(value):
        return await value
    return value


async def _call_page_method(page: Any, call: PlannedCall, *, phase: str, index: int | None = None) -> None:
    method = getattr(page, call.method, None)
    if method is None:
        raise BrowserWaitFailureError(f"page does not support {call.method}")

    try:
        result = method(*call.args, **(call.kwargs or {}))
        await _maybe_await(result)
    except WaitConditionsError:
        raise
    except (RuntimeError, TimeoutError, OSError, asyncio.TimeoutError, ConnectionError):
        # Keep deterministic; do not surface driver-specific exception strings.
        if index is None:
            raise BrowserWaitFailureError(f"browser failed during {phase}:{call.method}")
        raise BrowserWaitFailureError(f"browser failed during {phase}[{index}]:{call.method}")


async def apply_wait_calls_async(page: Any, calls: Sequence[PlannedCall]) -> None:
    for idx, call in enumerate(calls):
        await _call_page_method(page, call, phase="wait", index=idx)


async def execute_action_with_waits_async(page: Any, spec: ActionWithWaits) -> None:
    plan = plan_action_with_waits(spec)
    await _call_page_method(page, plan.action_call, phase="action")
    await apply_wait_calls_async(page, plan.wait_calls)


def execute_action_with_waits(page: Any, spec: ActionWithWaits) -> None:
    """
    Synchronous entrypoint.

    If page methods are async, this spins up an event loop via asyncio.run().
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        raise InvalidWaitConditionsError(
            "execute_action_with_waits cannot be called from a running event loop; use execute_action_with_waits_async"
        )

    asyncio.run(execute_action_with_waits_async(page, spec))


# ----------------------------
# JSON helpers
# ----------------------------


def spec_from_json(text: str) -> ActionWithWaits:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        raise InvalidWaitConditionsError("spec is not valid JSON")
    return parse_action_with_waits(raw)


def plan_to_dict(plan: ActionWaitPlan) -> dict[str, Any]:
    def call_to_dict(c: PlannedCall) -> dict[str, Any]:
        return {"method": c.method, "args": list(c.args), "kwargs": dict(c.kwargs or {})}

    return {"action": call_to_dict(plan.action_call), "waits": [call_to_dict(c) for c in plan.wait_calls]}


def error_to_dict(err: WaitConditionsError) -> dict[str, Any]:
    return asdict(err.to_error_info())


def action_with_waits_json_schema() -> dict[str, Any]:
    """
    JSON Schema describing the expected input spec.

    Intentionally flat (no $ref indirection) for easy embedding in automation.
    """
    return {
        "type": "object",
        "required": ["action"],
        "properties": {
            "action": {
                "type": "object",
                "required": ["kind"],
                "properties": {
                    "kind": {"type": "string", "enum": ["goto", "click", "fill", "press", "type", "select"]},
                    "selector": {"type": "string"},
                    "url": {"type": "string"},
                    "text": {"type": "string"},
                    "key": {"type": "string"},
                },
                "additionalProperties": False,
            },
            "waits": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["kind"],
                    "properties": {
                        "kind": {"type": "string", "enum": ["selector", "load_state", "url", "timeout"]},
                        "selector": {"type": "string"},
                        "state": {"type": "string"},
                        "url": {"type": "string"},
                        "timeout_ms": {"type": "integer", "minimum": 0},
                    },
                    "additionalProperties": False,
                },
            },
            "default_timeout_ms": {"type": "integer", "minimum": 0},
        },
        "additionalProperties": False,
    }


def action_with_waits_result_json_schema() -> dict[str, Any]:
    """JSON Schema describing the --json output for the CLI command."""
    return {
        "type": "object",
        "required": ["ok"],
        "properties": {
            "ok": {"type": "boolean"},
            "plan": {"type": "object"},
            "executed": {"type": "boolean"},
            "error": {
                "type": "object",
                "required": ["code", "message"],
                "properties": {"code": {"type": "string"}, "message": {"type": "string"}},
                "additionalProperties": False,
            },
        },
        "additionalProperties": False,
    }


__all__ = [
    "ActionWithWaits",
    "ActionWaitPlan",
    "BrowserAction",
    "BrowserWaitFailureError",
    "ErrorInfo",
    "InvalidWaitConditionsError",
    "MissingBrowserDriverError",
    "PlannedCall",
    "WaitCondition",
    "parse_action_with_waits",
    "plan_action_with_waits",
    "execute_action_with_waits",
    "execute_action_with_waits_async",
    "spec_from_json",
    "plan_to_dict",
    "error_to_dict",
    "action_with_waits_json_schema",
    "action_with_waits_result_json_schema",
]
