"""Runtime implementations for browser compatibility command surfaces.

These helpers back the P027-P035 browser command modules so those command names
perform real runtime work instead of placeholder no-op behavior.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import json
import sys
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BrowserCompatCommandError(RuntimeError):
    """Structured command failure used for stable JSON error output."""

    code: str
    category: str
    message: str
    exit_code: int
    hint: str = ""


@dataclass(frozen=True)
class BrowserSessionHandles:
    session_name: str
    session_state: Any
    page: Any
    context: Any


_ASYNC_LOOP: asyncio.AbstractEventLoop | None = None
_ASYNC_LOOP_THREAD: threading.Thread | None = None
_ASYNC_LOOP_READY = threading.Event()
_ASYNC_LOOP_LOCK = threading.Lock()


class _CompatArgumentParser(argparse.ArgumentParser):
    """argparse parser that raises typed errors instead of exiting directly."""

    def error(self, message: str) -> None:  # noqa: D401
        raise BrowserCompatCommandError(
            code="browser_command_invalid_input",
            category="invalid_input",
            message=str(message or "").strip() or "Invalid arguments.",
            exit_code=2,
        )


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _ensure_async_loop() -> asyncio.AbstractEventLoop:
    global _ASYNC_LOOP, _ASYNC_LOOP_THREAD

    with _ASYNC_LOOP_LOCK:
        if (
            _ASYNC_LOOP is not None
            and _ASYNC_LOOP_THREAD is not None
            and _ASYNC_LOOP_THREAD.is_alive()
            and not _ASYNC_LOOP.is_closed()
        ):
            return _ASYNC_LOOP

        _ASYNC_LOOP_READY.clear()

        def _runner() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            globals()["_ASYNC_LOOP"] = loop
            _ASYNC_LOOP_READY.set()
            loop.run_forever()

        thread = threading.Thread(target=_runner, name="browser-compat-loop", daemon=True)
        thread.start()
        _ASYNC_LOOP_THREAD = thread

    if not _ASYNC_LOOP_READY.wait(timeout=10):
        raise BrowserCompatCommandError(
            code="browser_runtime_loop_init_failed",
            category="external_failure",
            message="Timed out while starting browser runtime event loop.",
            exit_code=1,
        )

    if _ASYNC_LOOP is None:
        raise BrowserCompatCommandError(
            code="browser_runtime_loop_init_failed",
            category="external_failure",
            message="Browser runtime event loop failed to initialize.",
            exit_code=1,
        )
    return _ASYNC_LOOP


async def _await_value(value: Any) -> Any:
    return await value


def _await_if_needed(value: Any) -> Any:
    if not inspect.isawaitable(value):
        return value

    loop = _ensure_async_loop()
    future = asyncio.run_coroutine_threadsafe(_await_value(value), loop)
    try:
        return future.result(timeout=60)
    except TimeoutError as exc:
        future.cancel()
        raise BrowserCompatCommandError(
            code="browser_runtime_timeout",
            category="external_failure",
            message="Timed out while waiting for browser runtime operation.",
            exit_code=1,
        ) from exc


def _call_maybe_async(fn: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return _await_if_needed(fn(*args, **kwargs))
    except BrowserCompatCommandError:
        raise
    except Exception as exc:
        raise BrowserCompatCommandError(
            code="browser_runtime_call_failed",
            category="external_failure",
            message=f"{type(exc).__name__}: {exc}",
            exit_code=1,
        ) from exc


def _to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(v) for v in value]

    for attr in ("to_dict", "model_dump", "dict"):
        fn = getattr(value, attr, None)
        if callable(fn):
            try:
                return _to_jsonable(fn())
            except (ValueError, TypeError):
                continue
    return repr(value)


def _emit_payload(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        sys.stdout.write("\n")
        return

    if bool(payload.get("ok")):
        summary = str(payload.get("summary") or "").strip()
        if summary:
            sys.stdout.write(f"{summary}\n")
            return
        sys.stdout.write("ok\n")
        return

    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    code = str(error.get("code") or "browser_command_failed")
    message = str(error.get("message") or "Command failed.")
    sys.stderr.write(f"{code}: {message}\n")


def _error_payload(command: str, err: BrowserCompatCommandError) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": False,
        "command": command,
        "timestamp_utc": _utc_iso(),
        "error": {
            "category": str(err.category),
            "code": str(err.code),
            "message": str(err.message),
        },
    }
    hint = str(err.hint or "").strip()
    if hint:
        payload["error"]["hint"] = hint
    return payload


def _raise_invalid_input(message: str) -> None:
    raise BrowserCompatCommandError(
        code="browser_command_invalid_input",
        category="invalid_input",
        message=str(message or "").strip() or "Invalid input.",
        exit_code=2,
    )


def _resolve_session_name(browser_mod: Any, requested: str) -> str:
    req = str(requested or "").strip()
    if req:
        return req
    state = getattr(browser_mod, "_STATE", None)
    active = str(getattr(state, "active_session", "") or "").strip()
    return active or "default"


def _resolve_page_context(page: Any, session_state: Any) -> Any:
    context = getattr(session_state, "context", None)
    if context is not None:
        return context

    page_context = getattr(page, "context", None)
    if callable(page_context):
        return _call_maybe_async(page_context)
    if page_context is not None:
        return page_context
    return None


def _resolve_browser_handles(
    *,
    session_name: str = "",
    create_if_missing: bool,
) -> BrowserSessionHandles:
    try:
        browser_mod = importlib.import_module("thomas.tools.browser")
    except Exception as exc:
        raise BrowserCompatCommandError(
            code="browser_runtime_module_missing",
            category="missing_config",
            message=f"Browser runtime module unavailable: {type(exc).__name__}: {exc}",
            exit_code=3,
        ) from exc

    resolved_name = _resolve_session_name(browser_mod, session_name)

    if create_if_missing:
        ensure_session_page = getattr(browser_mod, "_ensure_session_page", None)
        if not callable(ensure_session_page):
            raise BrowserCompatCommandError(
                code="browser_runtime_helper_missing",
                category="missing_config",
                message="Browser runtime helper '_ensure_session_page' is not available.",
                exit_code=3,
            )
        try:
            value = _await_if_needed(ensure_session_page(resolved_name))
        except BrowserCompatCommandError:
            raise
        except Exception as exc:
            raise BrowserCompatCommandError(
                code="browser_session_create_failed",
                category="external_failure",
                message=f"Failed to initialize browser session '{resolved_name}': {type(exc).__name__}: {exc}",
                exit_code=1,
            ) from exc

        if not isinstance(value, tuple) or len(value) < 2 or value[0] is None or value[1] is None:
            raise BrowserCompatCommandError(
                code="browser_session_resolution_failed",
                category="external_failure",
                message="Browser runtime returned an unexpected session payload.",
                exit_code=1,
            )

        session_state = value[0]
        page = value[1]
    else:
        state = getattr(browser_mod, "_STATE", None)
        sessions = getattr(state, "sessions", None)
        if not isinstance(sessions, dict):
            raise BrowserCompatCommandError(
                code="browser_session_unavailable",
                category="missing_config",
                message="No browser sessions are available.",
                exit_code=3,
                hint="Run a browser command that opens a page before exporting artifacts.",
            )
        session_state = sessions.get(resolved_name)
        if session_state is None:
            raise BrowserCompatCommandError(
                code="browser_session_not_found",
                category="missing_config",
                message=f"Browser session '{resolved_name}' not found.",
                exit_code=3,
                hint="Use --session with an existing session name or start a new session first.",
            )
        page = getattr(session_state, "page", None)
        if page is None:
            raise BrowserCompatCommandError(
                code="browser_page_unavailable",
                category="missing_config",
                message=f"Browser session '{resolved_name}' has no active page.",
                exit_code=3,
            )

    context = _resolve_page_context(page, session_state)
    if context is None:
        raise BrowserCompatCommandError(
            code="browser_context_unavailable",
            category="missing_config",
            message=f"Browser context is unavailable for session '{resolved_name}'.",
            exit_code=3,
        )

    return BrowserSessionHandles(
        session_name=resolved_name,
        session_state=session_state,
        page=page,
        context=context,
    )


def _require_method(target: Any, name: str, *, code: str, message: str) -> Any:
    fn = getattr(target, name, None)
    if callable(fn):
        return fn
    raise BrowserCompatCommandError(
        code=code,
        category="not_supported",
        message=message,
        exit_code=4,
    )


def _permissions_get(session_state: Any) -> dict[str, list[str]]:
    current = getattr(session_state, "_thomas_permissions", None)
    if not isinstance(current, dict):
        return {}
    out: dict[str, list[str]] = {}
    for key, value in current.items():
        key_text = str(key or "").strip() or "*"
        if isinstance(value, list) or isinstance(value, set):
            rows = [str(x).strip() for x in value if str(x).strip()]
        else:
            rows = []
        out[key_text] = sorted(set(rows))
    return out


def _permissions_set(session_state: Any, value: dict[str, list[str]]) -> None:
    clean: dict[str, list[str]] = {}
    for key, rows in value.items():
        key_text = str(key or "").strip() or "*"
        clean[key_text] = sorted({str(x).strip() for x in rows if str(x).strip()})
    session_state._thomas_permissions = clean


def _resolve_output_path(raw: str, *, default_name: str) -> Path:
    target = str(raw or "").strip()
    if target:
        path = Path(target).expanduser()
    else:
        path = Path.cwd() / default_name
    if path.exists() and path.is_dir():
        path = path / default_name
    return path


def _extract_page_url(page: Any) -> str:
    try:
        value = getattr(page, "url", "")
        if callable(value):
            value = value()
        return str(value or "").strip()
    except (OSError, FileNotFoundError):
        return ""


def _extract_page_title(page: Any) -> str:
    title_fn = getattr(page, "title", None)
    if not callable(title_fn):
        return ""
    try:
        value = _call_maybe_async(title_fn)
        return str(value or "").strip()
    except (ValueError, TypeError):
        return ""


def _parse_json_value(raw: str, *, field_name: str) -> Any:
    try:
        return json.loads(raw)
    except Exception as exc:
        raise BrowserCompatCommandError(
            code="browser_command_invalid_input",
            category="invalid_input",
            message=f"{field_name} must be valid JSON: {exc}",
            exit_code=2,
        ) from exc


def _build_base_success(command: str, *, session_name: str) -> dict[str, Any]:
    return {
        "ok": True,
        "command": command,
        "session": session_name,
        "timestamp_utc": _utc_iso(),
    }


def _session_name_arg(args: Any) -> str:
    return str(getattr(args, "session_name", "") or "")


def _resolve_handles_for_args(args: Any, *, create_if_missing: bool = True) -> BrowserSessionHandles:
    return _resolve_browser_handles(
        session_name=_session_name_arg(args),
        create_if_missing=create_if_missing,
    )


def _build_session_success(
    command: str,
    handles: BrowserSessionHandles,
    *,
    summary: str,
    **extra: Any,
) -> dict[str, Any]:
    payload = _build_base_success(command, session_name=handles.session_name)
    payload["summary"] = str(summary)
    payload.update(extra)
    return payload


def _run_command(
    *,
    command: str,
    description: str,
    argv: Sequence[str] | None,
    configure: Any,
    execute: Any,
) -> int:
    argv_list = list(argv) if argv is not None else []
    json_requested = "--json" in argv_list
    parser = _CompatArgumentParser(prog=command, description=description)
    parser.add_argument("--json", dest="json_mode", action="store_true", default=False)
    configure(parser)
    try:
        args = parser.parse_args(argv_list)
        payload = execute(args)
        payload.setdefault("ok", True)
        payload.setdefault("command", command)
        payload.setdefault("timestamp_utc", _utc_iso())
        _emit_payload(payload, as_json=bool(getattr(args, "json_mode", False)))
        return 0
    except BrowserCompatCommandError as err:
        payload = _error_payload(command, err)
        _emit_payload(payload, as_json=json_requested)
        return int(err.exit_code)
    except Exception as exc:  # noqa: BLE001
        err = BrowserCompatCommandError(
            code="browser_runtime_unexpected_error",
            category="external_failure",
            message=f"{type(exc).__name__}: {exc}",
            exit_code=1,
        )
        payload = _error_payload(command, err)
        _emit_payload(payload, as_json=json_requested)
        return int(err.exit_code)


# Export helper symbols (including underscore-prefixed runtime helpers) so
# split command entrypoint modules can import them via `from ... import *`.
__all__ = [name for name in globals() if not name.startswith("__")]
