"""Thomas browser click action.

Implements a *Thomas-native* "click" behaviour that can be used by:
- the Thomas CLI ("browser click"), and/or
- an automation/router layer (JSON schema + dict I/O).

Key properties:
- Clear typed contracts (dataclasses).
- Deterministic error *kinds* for automation.
- Minimal assumptions about the upstream browser client (duck-typed adapter).

This module intentionally uses Thomas-native naming.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Union, cast

__all__ = [
    "ACTION_NAME",
    "BrowserClickError",
    "ClickConfigError",
    "ClickErrorInfo",
    "ClickExternalError",
    "ClickInputError",
    "ClickRequest",
    "ClickResponse",
    "ClickTarget",
    "click",
    "click_json",
    "click_to_dict",
    "error_info",
    "input_schema",
    "json_schema",
    "output_schema",
    "parse_click_request",
    "parse_click_target",
    "run",
]


ACTION_NAME = "browser.click"


# ---------------------------------------------------------------------------
# Input / output contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClickTarget:
    """A single click target.

    Exactly one of `node_id` or `selector` must be provided.

    Attributes:
        node_id: An integer node id produced by element enumeration / node listing.
        selector: A CSS selector string.
    """

    node_id: int | None = None
    selector: str | None = None


@dataclass(frozen=True)
class ClickRequest:
    """Request contract for a click action.

    Attributes:
        target: What to click (node id or selector).
        timeout_ms: Timeout budget in milliseconds (positive integer).
    """

    target: ClickTarget
    timeout_ms: int = 30_000


@dataclass(frozen=True)
class ClickResponse:
    """Response contract for a click action."""

    ok: bool
    clicked: bool
    used: str
    target: ClickTarget
    details: str = ""


@dataclass(frozen=True)
class ClickErrorInfo:
    """Machine-readable error payload."""

    kind: str
    message: str


# ---------------------------------------------------------------------------
# Deterministic errors
# ---------------------------------------------------------------------------


class BrowserClickError(RuntimeError):
    """Base exception for click action failures.

    The `kind` attribute is stable and intended for automation.
    """

    kind: str = "browser_click_error"

    def __init__(self, message: str):
        super().__init__(message)


class ClickInputError(BrowserClickError):
    kind = "invalid_input"


class ClickConfigError(BrowserClickError):
    kind = "missing_config"


class ClickExternalError(BrowserClickError):
    kind = "external_failure"


def error_info(exc: BrowserClickError) -> ClickErrorInfo:
    return ClickErrorInfo(kind=getattr(exc, "kind", "error"), message=str(exc))


# ---------------------------------------------------------------------------
# Public API (typed)
# ---------------------------------------------------------------------------


def click(request: ClickRequest, *, browser: Any | None = None) -> ClickResponse:
    """Perform a click in the live browser.

    Args:
        request: Click request.
        browser: Optional browser/session object. When omitted, we attempt to
            resolve an active browser session from the Thomas runtime.

    Returns:
        ClickResponse

    Raises:
        ClickInputError: Invalid request.
        ClickConfigError: Missing browser session / configuration.
        ClickExternalError: Underlying browser driver raised.
    """

    _validate_request(request)

    client = browser if browser is not None else _resolve_browser_client()

    target = request.target

    try:
        if target.node_id is not None:
            _click_by_node_id(client, target.node_id)
            used = "node_id"
        else:
            # validated: exactly one
            selector = cast(str, target.selector)
            _click_by_selector(client, selector)
            used = "selector"
    except BrowserClickError:
        raise
    except Exception as e:  # pragma: no cover
        raise ClickExternalError(_format_external_error("Click failed", e)) from e

    return ClickResponse(
        ok=True,
        clicked=True,
        used=used,
        target=target,
        details="clicked",
    )


# ---------------------------------------------------------------------------
# Public API (automation-friendly)
# ---------------------------------------------------------------------------


JSONValue = Union[None, bool, int, float, str, dict[str, Any], list]


def click_to_dict(request: ClickRequest, *, browser: Any | None = None) -> dict[str, Any]:
    """Like :func:`click`, but returns a plain dict instead of raising.

    Success payload matches :func:`dataclasses.asdict(ClickResponse)`.

    Failure payload shape:

        {"ok": False, "clicked": False, "error": {"kind": "...", "message": "..."}}

    This is designed to be safe for machine automation.
    """
    try:
        result = click(request, browser=browser)
        return cast(dict[str, Any], asdict(result))
    except BrowserClickError as e:
        return {"ok": False, "clicked": False, "error": asdict(error_info(e))}


def click_json(request: ClickRequest, *, browser: Any | None = None) -> str:
    """Like :func:`click_to_dict`, but returns a JSON string."""
    return json.dumps(click_to_dict(request, browser=browser), sort_keys=True)


def parse_click_target(value: Any) -> ClickTarget:
    """Parse a click target from typical untyped inputs.

    Accepted forms:
    - ClickTarget instance
    - dict with keys "node_id"/"selector"
    - int
    - str (digits => node_id, otherwise selector)
    """
    if isinstance(value, ClickTarget):
        return value

    if isinstance(value, Mapping):
        node_id = value.get("node_id")
        selector = value.get("selector")
        # Do not coerce too aggressively; validate later.
        return ClickTarget(node_id=node_id, selector=selector)  # type: ignore[arg-type]

    if isinstance(value, bool):
        # bool is a subclass of int; treat as invalid input early.
        return ClickTarget(node_id=None, selector=str(value))

    if isinstance(value, int):
        return ClickTarget(node_id=value)

    if isinstance(value, str):
        raw = value.strip()
        if raw.isdigit():
            return ClickTarget(node_id=int(raw))
        return ClickTarget(selector=raw)

    # Unknown type: force validation failure.
    return ClickTarget(selector=str(value))


def parse_click_request(payload: Any) -> ClickRequest:
    """Parse a ClickRequest from an untyped payload.

    Accepted forms:
    - ClickRequest instance
    - dict with keys: "target" (required), "timeout_ms" (optional)
    """
    if isinstance(payload, ClickRequest):
        return payload

    if not isinstance(payload, Mapping):
        raise ClickInputError("request payload must be an object (mapping)")

    if "target" not in payload:
        raise ClickInputError("request.target is required")

    target = parse_click_target(payload.get("target"))
    timeout_ms = payload.get("timeout_ms", 30_000)

    # Preserve original type if possible; validation will reject invalid.
    return ClickRequest(target=target, timeout_ms=cast(int, timeout_ms))


def run(payload: Any, *, browser: Any | None = None) -> dict[str, Any]:
    """Entry point for route-based automation.

    Args:
        payload: dict-like payload with request fields.
        browser: optional browser client.

    Returns:
        A dict response payload (never raises BrowserClickError).
    """
    try:
        req = parse_click_request(payload)
    except BrowserClickError as e:
        return {"ok": False, "clicked": False, "error": asdict(error_info(e))}

    return click_to_dict(req, browser=browser)


def input_schema() -> dict[str, Any]:
    """JSON schema for the click request payload accepted by :func:`run`."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Thomas Browser Click Request",
        "type": "object",
        "properties": {
            "target": {
                "type": "object",
                "properties": {
                    "node_id": {"type": ["integer", "null"], "minimum": 0},
                    "selector": {"type": ["string", "null"], "minLength": 1},
                },
                "additionalProperties": False,
            },
            "timeout_ms": {"type": "integer", "minimum": 1},
        },
        "required": ["target"],
        "additionalProperties": False,
    }


def output_schema() -> dict[str, Any]:
    """JSON schema for the response payload returned by :func:`run`."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Thomas Browser Click Response",
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "clicked": {"type": "boolean"},
            "used": {"type": "string"},
            "target": input_schema()["properties"]["target"],
            "details": {"type": "string"},
            "error": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string"},
                    "message": {"type": "string"},
                },
                "required": ["kind", "message"],
                "additionalProperties": False,
            },
        },
        "required": ["ok", "clicked"],
        "additionalProperties": False,
    }


def json_schema() -> dict[str, Any]:
    """Combined schema document describing both request and response."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Thomas Browser Click",
        "type": "object",
        "properties": {
            "request": input_schema(),
            "response": output_schema(),
        },
        "required": ["request", "response"],
        "additionalProperties": False,
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_request(request: ClickRequest) -> None:
    if not isinstance(request.timeout_ms, int) or isinstance(request.timeout_ms, bool):
        raise ClickInputError("timeout_ms must be an integer")
    if request.timeout_ms <= 0:
        raise ClickInputError("timeout_ms must be a positive integer")

    target = request.target
    has_node = target.node_id is not None
    has_selector = target.selector is not None

    if has_node == has_selector:
        raise ClickInputError("Exactly one of target.node_id or target.selector must be provided")

    if has_node:
        node_id = target.node_id
        if not isinstance(node_id, int) or isinstance(node_id, bool):
            raise ClickInputError("target.node_id must be an integer")
        if node_id < 0:
            raise ClickInputError("target.node_id must be >= 0")

    if has_selector:
        selector = target.selector
        if not isinstance(selector, str) or not selector.strip():
            raise ClickInputError("target.selector must be a non-empty string")


# ---------------------------------------------------------------------------
# Browser/session resolution
# ---------------------------------------------------------------------------


def _resolve_browser_client() -> Any:
    """Resolve an active browser client from the Thomas runtime.

    We keep this tolerant to integrate with varying upstream implementations.

    Resolution strategy:
    1) Attempt to import `thomas.cli.live_browser` and find a no-arg getter.
    2) Attempt to import `thomas.tools.browser` and find a no-arg getter.
    3) Fall back to commonly-named module globals.

    Raises:
        ClickConfigError if no client can be resolved.
    """
    # Module -> candidate attribute names (callable getter preferred, else object)
    candidates = [
        ("thomas.cli.live_browser", ["get_live_browser", "get_browser", "live_browser", "BROWSER", "browser"]),
        ("thomas.tools.browser", ["get_default_browser", "get_browser", "default_browser", "BROWSER", "browser"]),
    ]

    for module_name, attr_names in candidates:
        mod = _safe_import(module_name)
        if mod is None:
            continue

        # Prefer callables.
        for name in attr_names:
            attr = getattr(mod, name, None)
            if callable(attr):
                try:
                    client = attr()
                except TypeError:
                    # requires args; skip
                    continue
                except (RuntimeError, AttributeError, ImportError):
                    # getter exists but failed; skip and keep looking
                    continue
                if client is not None:
                    return client

        # Then try objects.
        for name in attr_names:
            attr = getattr(mod, name, None)
            if attr is not None and not callable(attr):
                return attr

    raise ClickConfigError(
        "No active browser session found. Start a live browser session or pass an explicit browser client."
    )


def _safe_import(module_name: str) -> Any | None:
    try:
        return importlib.import_module(module_name)
    except (ImportError, ModuleNotFoundError):
        return None


# ---------------------------------------------------------------------------
# Click adapters (duck typing)
# ---------------------------------------------------------------------------


def _click_by_node_id(client: Any, node_id: int) -> None:
    """Click by node id using duck-typed browser client methods."""
    # Common method names in browser abstractions.
    for method_name in (
        "click_node",
        "click_by_node",
        "click_by_node_id",
        "click_node_id",
        "click_index",
        "click_by_index",
    ):
        method = getattr(client, method_name, None)
        if callable(method):
            try:
                method(node_id)
            except Exception as e:
                raise ClickExternalError(_format_external_error(f"Browser click via {method_name} failed", e)) from e
            return

    # Last resort: try generic click; some implementations accept int ids.
    method = getattr(client, "click", None)
    if callable(method):
        try:
            method(node_id)  # type: ignore[arg-type]
        except TypeError as e:
            raise ClickExternalError(
                "Browser client does not support node-id clicks (no click_node/click_by_node_id)."
            ) from e
        except Exception as e:
            raise ClickExternalError(_format_external_error("Browser click failed", e)) from e
        return

    raise ClickExternalError("Browser client does not expose a supported click method")


def _click_by_selector(client: Any, selector: str) -> None:
    """Click by selector using duck-typed browser client methods."""
    for method_name in ("click", "click_selector", "click_by_selector", "click_css", "click_by_css"):
        method = getattr(client, method_name, None)
        if callable(method):
            try:
                method(selector)
            except Exception as e:
                raise ClickExternalError(_format_external_error(f"Browser click via {method_name} failed", e)) from e
            return

    raise ClickExternalError("Browser client does not expose a supported selector click method")


def _format_external_error(prefix: str, exc: BaseException) -> str:
    """Create a deterministic external failure message.

    We include the exception class name and a sanitized snippet of the message.
    """
    exc_type = type(exc).__name__
    msg = str(exc).strip().replace("\n", " ")
    if msg:
        if len(msg) > 200:
            msg = msg[:200] + "..."
        return f"{prefix} ({exc_type}): {msg}"
    return f"{prefix} ({exc_type})"
