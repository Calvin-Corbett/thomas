"""thomas.browser.p005_browser_action_hover_and_focus

P005 implements two element-level browser actions:

- **hover**: move the pointer over an element.
- **focus**: move keyboard focus to an element.

This module is intentionally *backend-agnostic*. It does not assume Playwright,
Selenium, CDP, etc. Instead it uses duck-typing to find a suitable method on
whatever "browser/controller" object Thomas provides.

Design goals:
- Clear input/output contracts (dataclasses + TypedDicts)
- Deterministic errors for invalid input, missing configuration, and
  external/browser failures.

"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

HoverFocusAction = Literal["hover", "focus"]


class HoverFocusTarget(TypedDict, total=False):
    selector: str
    node_id: int | str


class HoverFocusErrorInfo(TypedDict):
    code: Literal["invalid_input", "missing_config", "external_failure"]
    message: str


class HoverFocusSuccessPayload(TypedDict):
    ok: Literal[True]
    action: HoverFocusAction
    target: HoverFocusTarget
    backend_call: str


class HoverFocusErrorPayload(TypedDict):
    ok: Literal[False]
    action: HoverFocusAction
    error: HoverFocusErrorInfo


@dataclass(frozen=True, slots=True)
class HoverFocusRequest:
    """Input contract for hover/focus.

    Exactly one of ``selector`` or ``node_id`` must be provided.

    ``timeout_ms`` is optional because not every backend supports timeouts.
    """

    action: HoverFocusAction
    selector: str | None = None
    node_id: int | str | None = None
    timeout_ms: int | None = None

    def validate(self) -> None:
        if self.action not in ("hover", "focus"):
            raise HoverFocusError.invalid_input("action must be one of: hover, focus")

        if (self.selector is None) == (self.node_id is None):
            # either both None or both set
            raise HoverFocusError.invalid_input("exactly one of selector or node_id must be provided")

        if self.selector is not None:
            if not isinstance(self.selector, str) or not self.selector.strip():
                raise HoverFocusError.invalid_input("selector must be a non-empty string")

        if self.node_id is not None:
            if not isinstance(self.node_id, (int, str)):
                raise HoverFocusError.invalid_input("node_id must be a string or integer")
            if isinstance(self.node_id, str) and not self.node_id.strip():
                raise HoverFocusError.invalid_input("node_id must be a non-empty string")

        if self.timeout_ms is not None:
            if not isinstance(self.timeout_ms, int) or self.timeout_ms <= 0:
                raise HoverFocusError.invalid_input("timeout_ms must be a positive integer")


@dataclass(frozen=True, slots=True)
class HoverFocusResult:
    """Output contract for a successful action."""

    action: HoverFocusAction
    target: HoverFocusTarget
    backend_call: str

    def to_payload(self) -> HoverFocusSuccessPayload:
        return {
            "ok": True,
            "action": self.action,
            "target": dict(self.target),
            "backend_call": self.backend_call,
        }


class HoverFocusError(RuntimeError):
    """Deterministic exception used by this feature."""

    __slots__ = ("code", "message")

    def __init__(
        self,
        code: Literal["invalid_input", "missing_config", "external_failure"],
        message: str,
    ):
        super().__init__(message)
        self.code = code
        self.message = message

    @property
    def exit_code(self) -> int:
        # Conventional CLI semantics: usage errors -> 2, runtime -> 1.
        return 2 if self.code == "invalid_input" else 1

    def to_payload(self, *, action: HoverFocusAction) -> HoverFocusErrorPayload:
        return {
            "ok": False,
            "action": action,
            "error": {"code": self.code, "message": self.message},
        }

    @staticmethod
    def invalid_input(message: str) -> HoverFocusError:
        return HoverFocusError("invalid_input", message)

    @staticmethod
    def missing_config(message: str) -> HoverFocusError:
        return HoverFocusError("missing_config", message)

    @staticmethod
    def external_failure(message: str) -> HoverFocusError:
        return HoverFocusError("external_failure", message)


# Optional schemas that tool routers can reuse (in addition to CLI --json).
REQUEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "action": {"type": "string", "enum": ["hover", "focus"]},
        "selector": {"type": "string"},
        "node_id": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
        "timeout_ms": {"type": "integer", "minimum": 1},
    },
    "required": ["action"],
}

RESPONSE_SCHEMA: dict[str, Any] = {
    "oneOf": [
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "ok": {"const": True},
                "action": {"type": "string", "enum": ["hover", "focus"]},
                "target": {"type": "object"},
                "backend_call": {"type": "string"},
            },
            "required": ["ok", "action", "target", "backend_call"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "ok": {"const": False},
                "action": {"type": "string", "enum": ["hover", "focus"]},
                "error": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "code": {
                            "type": "string",
                            "enum": [
                                "invalid_input",
                                "missing_config",
                                "external_failure",
                            ],
                        },
                        "message": {"type": "string"},
                    },
                    "required": ["code", "message"],
                },
            },
            "required": ["ok", "action", "error"],
        },
    ]
}


async def hover_or_focus(browser: Any, request: HoverFocusRequest) -> HoverFocusResult:
    """Execute hover/focus on a provided browser/controller.

    The function is async because most modern browser drivers are async.
    """

    request.validate()

    if browser is None:
        raise HoverFocusError.missing_config("no active browser session/controller was provided")

    if request.selector is not None:
        target_kind: Literal["selector", "node_id"] = "selector"
        target_value: int | str = request.selector
    else:
        target_kind = "node_id"
        target_value = request.node_id  # type: ignore[assignment]

    backend_call = await _dispatch(
        browser,
        request.action,
        target_kind,
        target_value,
        request.timeout_ms,
    )

    target: HoverFocusTarget = {target_kind: target_value}
    return HoverFocusResult(action=request.action, target=target, backend_call=backend_call)


def hover_or_focus_sync(browser: Any, request: HoverFocusRequest) -> HoverFocusResult:
    """Synchronous wrapper used by CLI code."""

    try:
        import anyio  # type: ignore

        return anyio.run(hover_or_focus, browser, request)
    except ImportError:
        import asyncio

        return asyncio.run(hover_or_focus(browser, request))


def request_from_mapping(data: Mapping[str, Any]) -> HoverFocusRequest:
    """Parse an untrusted mapping into a request."""

    action = data.get("action")
    selector = data.get("selector")
    node_id = data.get("node_id")
    timeout_ms = data.get("timeout_ms")

    if timeout_ms is not None and not isinstance(timeout_ms, int):
        # Keep deterministic: coerce numeric strings, otherwise invalid.
        if isinstance(timeout_ms, str) and timeout_ms.isdigit():
            timeout_ms = int(timeout_ms)
        else:
            raise HoverFocusError.invalid_input("timeout_ms must be a positive integer")

    return HoverFocusRequest(
        action=action,  # type: ignore[arg-type]
        selector=selector if isinstance(selector, str) else None,
        node_id=node_id,
        timeout_ms=timeout_ms,
    )


# A small, opt-in registry surface for any dispatcher that scans modules.
ACTION_HANDLERS: Mapping[HoverFocusAction, Callable[[Any, HoverFocusRequest], Awaitable[HoverFocusResult]]] = {
    "hover": hover_or_focus,
    "focus": hover_or_focus,
}


def _call_variants(
    *,
    target_kind: Literal["selector", "node_id"],
    target_value: str | int,
    timeout_ms: int | None,
) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
    """Return call variants ordered from most-specific to least."""

    variants: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    if target_kind == "selector":
        # Most libraries accept selector positional.
        if timeout_ms is not None:
            variants.append(((target_value,), {"timeout_ms": timeout_ms}))
            variants.append(((target_value,), {"timeout": timeout_ms}))
        variants.append(((target_value,), {}))
    else:
        # Node-id based APIs vary; try kwargs first.
        if timeout_ms is not None:
            variants.append(((), {"node_id": target_value, "timeout_ms": timeout_ms}))
            variants.append(((), {"node_id": target_value, "timeout": timeout_ms}))
        variants.append(((), {"node_id": target_value}))
        variants.append(((target_value,), {}))

    return variants


async def _maybe_await(value: Any) -> None:
    if inspect.isawaitable(value):
        await value


def _bindability(fn: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Literal["bindable", "unbound", "unknown"]:
    """Classify whether a call *should* be legal.

    - bindable: signature introspection says it should accept args/kwargs
    - unbound: signature introspection says it will not accept args/kwargs
    - unknown: signature introspection not available

    This helps us avoid treating genuine backend TypeErrors as "signature mismatch".
    """

    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return "unknown"

    try:
        sig.bind(*args, **kwargs)
        return "bindable"
    except TypeError:
        return "unbound"


async def _dispatch(
    browser: Any,
    action: HoverFocusAction,
    target_kind: Literal["selector", "node_id"],
    target_value: str | int,
    timeout_ms: int | None,
) -> str:
    """Try a series of backend call patterns.

    Returns a string describing which backend call succeeded.
    """

    backend_objects: list[tuple[str, Any]] = [("browser", browser)]

    for attr in ("page", "_page", "driver", "_driver"):
        try:
            obj = getattr(browser, attr)
        except AttributeError:
            obj = None
        if obj is not None:
            backend_objects.append((f"browser.{attr}", obj))

    # 1) Direct method on browser-like objects
    for obj_name, obj in backend_objects:
        method = getattr(obj, action, None)
        if not callable(method):
            continue

        last_typeerror: BaseException | None = None

        for args, kwargs in _call_variants(
            target_kind=target_kind,
            target_value=target_value,
            timeout_ms=timeout_ms,
        ):
            bind_state = _bindability(method, args, kwargs)
            if bind_state == "unbound":
                continue

            try:
                await _maybe_await(method(*args, **kwargs))
                return f"{obj_name}.{action}"
            except HoverFocusError:
                raise
            except TypeError as exc:
                # If signature is unknown, a TypeError could be mismatch.
                if bind_state == "unknown":
                    last_typeerror = exc
                    continue
                raise HoverFocusError.external_failure(f"browser {action} failed ({type(exc).__name__})") from exc
            except Exception as exc:
                raise HoverFocusError.external_failure(f"browser {action} failed ({type(exc).__name__})") from exc

        # If we found the method but all variants TypeErrored with unknown
        # signature, keep looking at other backend objects.
        if last_typeerror is not None:
            continue

    # 2) Generic dispatchers
    dispatch_names = (
        "perform_action",
        "perform",
        "run_action",
        "execute_action",
        "execute",
        "action",
        "do",
    )

    for disp_name in dispatch_names:
        dispatcher = getattr(browser, disp_name, None)
        if not callable(dispatcher):
            continue

        payload: dict[str, Any] = {target_kind: target_value}
        if timeout_ms is not None:
            payload["timeout_ms"] = timeout_ms

        variants: list[tuple[tuple[Any, ...], dict[str, Any]]] = [
            ((action,), payload),
            ((), {"action": action, **payload}),
            ((), {"name": action, **payload}),
        ]

        for args, kwargs in variants:
            bind_state = _bindability(dispatcher, args, kwargs)
            if bind_state == "unbound":
                continue

            try:
                await _maybe_await(dispatcher(*args, **kwargs))
                return f"browser.{disp_name}"
            except TypeError as exc:
                if bind_state == "unknown":
                    continue
                raise HoverFocusError.external_failure(f"browser {action} failed ({type(exc).__name__})") from exc
            except Exception as exc:
                raise HoverFocusError.external_failure(f"browser {action} failed ({type(exc).__name__})") from exc

    raise HoverFocusError.external_failure(f"browser backend does not support action '{action}'")
