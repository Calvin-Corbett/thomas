"""Browser action: type text into an element and press a key.

This is a small, Thomas-native action primitive intended for:
  * CLI usage
  * node/graph runners
  * higher-level browser tooling

The runtime target is expected to be a Playwright-like Page object (sync API),
but the action is tolerant of Thomas wrapper objects that expose a `.page`
attribute.

Deterministic failures are surfaced via :class:`TypeAndPressError` with a stable
error code suitable for automation.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, NotRequired, TypedDict, Literal, cast


ACTION_NAME = "type_and_press"


ErrorCode = Literal[
    "INVALID_INPUT",
    "MISSING_BROWSER",
    "INVALID_TARGET",
    "MISSING_CONFIG",
    "CONFIG_INVALID",
    "TIMEOUT",
    "EXTERNAL_FAILURE",
]


class TypeAndPressParamsDict(TypedDict):
    """Machine-friendly input contract."""

    selector: str
    text: str
    key: NotRequired[str]
    timeout_ms: NotRequired[int]
    delay_ms: NotRequired[int]
    click_first: NotRequired[bool]


class TypeAndPressSuccessDict(TypedDict):
    """Machine-friendly success output contract."""

    ok: bool
    selector: str
    text: str
    key: str


class TypeAndPressFailureDict(TypedDict):
    """Machine-friendly failure output contract."""

    ok: bool
    code: ErrorCode
    message: str
    step: NotRequired[str]


TypeAndPressOutputDict = TypeAndPressSuccessDict | TypeAndPressFailureDict


@dataclass(frozen=True, slots=True)
class TypeAndPressParams:
    selector: str
    text: str
    key: str = "Enter"
    timeout_ms: int | None = None
    delay_ms: int | None = None
    click_first: bool = True


@dataclass(frozen=True, slots=True)
class TypeAndPressResult:
    ok: bool
    selector: str
    text: str
    key: str

    def to_dict(self) -> TypeAndPressSuccessDict:
        return {"ok": self.ok, "selector": self.selector, "text": self.text, "key": self.key}


class TypeAndPressError(Exception):
    """Deterministic error for the action.

    Attributes:
        code: A stable machine-readable error code.
        message: Human-readable message.
        step: Optional step label for additional debugging context.
    """

    def __init__(self, *, code: ErrorCode, message: str, step: str | None = None):
        super().__init__(f"{code}: {message}")
        self.code: ErrorCode = code
        self.message: str = message
        self.step: str | None = step

    def to_dict(self) -> TypeAndPressFailureDict:
        payload: TypeAndPressFailureDict = {"ok": False, "code": self.code, "message": self.message}
        if self.step:
            payload["step"] = self.step
        return payload


def input_json_schema() -> dict[str, Any]:
    """Input JSON schema for automation clients."""

    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["selector", "text"],
        "properties": {
            "selector": {"type": "string", "minLength": 1},
            "text": {"type": "string"},
            "key": {"type": "string", "default": "Enter"},
            "timeout_ms": {"type": "integer", "minimum": 1},
            "delay_ms": {"type": "integer", "minimum": 0},
            "click_first": {"type": "boolean", "default": True},
        },
    }


def output_json_schema() -> dict[str, Any]:
    """Success output JSON schema for automation clients."""

    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["ok", "selector", "text", "key"],
        "properties": {
            "ok": {"type": "boolean"},
            "selector": {"type": "string"},
            "text": {"type": "string"},
            "key": {"type": "string"},
        },
    }


INPUT_SCHEMA = input_json_schema()
OUTPUT_SCHEMA = output_json_schema()


def parse_params(data: Mapping[str, Any]) -> TypeAndPressParams:
    """Validate and coerce a mapping into :class:`TypeAndPressParams`."""

    selector = data.get("selector")
    text = data.get("text")
    key = data.get("key", "Enter")
    timeout_ms = data.get("timeout_ms")
    delay_ms = data.get("delay_ms")
    click_first = data.get("click_first", True)

    if not isinstance(selector, str) or not selector.strip():
        raise TypeAndPressError(code="INVALID_INPUT", message="selector must be a non-empty string", step="validate")
    if not isinstance(text, str):
        raise TypeAndPressError(code="INVALID_INPUT", message="text must be a string", step="validate")
    if not isinstance(key, str) or not key.strip():
        raise TypeAndPressError(code="INVALID_INPUT", message="key must be a non-empty string", step="validate")
    if timeout_ms is not None and (not isinstance(timeout_ms, int) or timeout_ms <= 0):
        raise TypeAndPressError(code="INVALID_INPUT", message="timeout_ms must be a positive integer", step="validate")
    if delay_ms is not None and (not isinstance(delay_ms, int) or not delay_ms >= 0):
        raise TypeAndPressError(code="INVALID_INPUT", message="delay_ms must be a non-negative integer", step="validate")
    if not isinstance(click_first, bool):
        raise TypeAndPressError(code="INVALID_INPUT", message="click_first must be a boolean", step="validate")

    return TypeAndPressParams(
        selector=cast(str, selector),
        text=text,
        key=cast(str, key).strip(),
        timeout_ms=cast(int | None, timeout_ms),
        delay_ms=cast(int | None, delay_ms),
        click_first=cast(bool, click_first),
    )


def _coerce_page(browser_or_page: Any) -> Any:
    """Accept either a Playwright Page or a Thomas wrapper exposing `.page`."""

    if browser_or_page is None:
        raise TypeAndPressError(code="MISSING_BROWSER", message="No browser/page provided", step="coerce_page")

    maybe_page = getattr(browser_or_page, "page", None)
    return maybe_page if maybe_page is not None else browser_or_page


def _timeout_error_type() -> type[BaseException] | None:
    """Best-effort import of Playwright TimeoutError without hard dependency."""

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError  # type: ignore
    except Exception:
        return None
    return PlaywrightTimeoutError


def _classify_external_failure(exc: BaseException) -> tuple[ErrorCode, str]:
    timeout_type = _timeout_error_type()
    if timeout_type is not None and isinstance(exc, timeout_type):
        return ("TIMEOUT", str(exc) or exc.__class__.__name__)
    return ("EXTERNAL_FAILURE", str(exc) or exc.__class__.__name__)


def type_and_press(browser_or_page: Any, params: TypeAndPressParams) -> TypeAndPressResult:
    """Type into `params.selector` and press `params.key`.

    Raises:
        TypeAndPressError: deterministic error with stable code.
    """

    page = _coerce_page(browser_or_page)
    if not hasattr(page, "locator"):
        raise TypeAndPressError(
            code="INVALID_TARGET",
            message="Provided browser/page does not appear to be a Playwright Page (missing .locator)",
            step="validate_target",
        )

    try:
        locator = page.locator(params.selector)
    except Exception as exc:
        code, msg = _classify_external_failure(exc)
        raise TypeAndPressError(code=code, message=f"Failed to create locator: {msg}", step="locator")

    # Some Playwright operations already wait implicitly, but a short explicit wait
    # helps make failures more predictable (e.g., element not attached yet).
    try:
        if hasattr(locator, "wait_for"):
            wait_kwargs: dict[str, Any] = {}
            if params.timeout_ms is not None:
                wait_kwargs["timeout"] = params.timeout_ms
            # 'attached' is permissive; visibility is handled by click/fill anyway.
            locator.wait_for(state="attached", **wait_kwargs)
    except Exception as exc:
        code, msg = _classify_external_failure(exc)
        raise TypeAndPressError(code=code, message=f"Element did not become attached: {msg}", step="wait_for")

    try:
        if params.click_first and hasattr(locator, "click"):
            click_kwargs: dict[str, Any] = {}
            if params.timeout_ms is not None:
                click_kwargs["timeout"] = params.timeout_ms
            locator.click(**click_kwargs)
    except Exception as exc:
        code, msg = _classify_external_failure(exc)
        raise TypeAndPressError(code=code, message=f"Click failed: {msg}", step="click")

    # Prefer fill(); fall back to type() when fill isn't supported.
    typed = False
    last_exc: BaseException | None = None

    if hasattr(locator, "fill"):
        try:
            fill_kwargs: dict[str, Any] = {}
            if params.timeout_ms is not None:
                fill_kwargs["timeout"] = params.timeout_ms
            locator.fill(params.text, **fill_kwargs)
            typed = True
        except Exception as exc:
            last_exc = exc

    if not typed and hasattr(locator, "type"):
        try:
            type_kwargs: dict[str, Any] = {}
            if params.timeout_ms is not None:
                type_kwargs["timeout"] = params.timeout_ms
            if params.delay_ms is not None:
                type_kwargs["delay"] = params.delay_ms
            locator.type(params.text, **type_kwargs)
            typed = True
        except Exception as exc:
            last_exc = exc

    if not typed:
        if last_exc is None:
            raise TypeAndPressError(
                code="INVALID_TARGET",
                message="Element does not support typing (missing locator.fill/locator.type)",
                step="type",
            )
        code, msg = _classify_external_failure(last_exc)
        raise TypeAndPressError(code=code, message=f"Typing failed: {msg}", step="type")

    try:
        press_kwargs: dict[str, Any] = {}
        if params.timeout_ms is not None:
            press_kwargs["timeout"] = params.timeout_ms

        if hasattr(locator, "press"):
            locator.press(params.key, **press_kwargs)
        elif hasattr(page, "keyboard") and hasattr(page.keyboard, "press"):
            page.keyboard.press(params.key)
        else:
            raise TypeAndPressError(
                code="INVALID_TARGET",
                message="Cannot press key: neither locator.press nor page.keyboard.press is available",
                step="press",
            )
    except TypeAndPressError:
        raise
    except Exception as exc:
        code, msg = _classify_external_failure(exc)
        raise TypeAndPressError(code=code, message=f"Press failed: {msg}", step="press")

    return TypeAndPressResult(ok=True, selector=params.selector, text=params.text, key=params.key)


def run(browser_or_page: Any, raw_params: TypeAndPressParamsDict | Mapping[str, Any]) -> TypeAndPressSuccessDict:
    """Strict runner: returns success output or raises :class:`TypeAndPressError`."""

    params = parse_params(cast(Mapping[str, Any], raw_params))
    return type_and_press(browser_or_page, params).to_dict()


def safe_run(browser_or_page: Any, raw_params: TypeAndPressParamsDict | Mapping[str, Any]) -> TypeAndPressOutputDict:
    """Safe runner: never raises; returns either success or failure dict."""

    try:
        return run(browser_or_page, raw_params)
    except TypeAndPressError as exc:
        return exc.to_dict()


def format_json(payload: TypeAndPressOutputDict | TypeAndPressResult | TypeAndPressError) -> str:
    """Stable JSON formatting for CLI/automation."""

    if isinstance(payload, TypeAndPressResult):
        data: Any = payload.to_dict()
    elif isinstance(payload, TypeAndPressError):
        data = payload.to_dict()
    else:
        data = payload
    return json.dumps(data, sort_keys=True, ensure_ascii=False)
