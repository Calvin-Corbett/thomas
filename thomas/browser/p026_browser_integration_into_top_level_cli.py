"""Browser integration core logic for the Thomas CLI (P026).

This module provides a small, stable contract that the top-level CLI can call
to open a URL using the best available browser backend.

Backend order:
1) Thomas browser tool (thomas.tools.browser) when available.
2) Python stdlib webbrowser as a fallback.

The function returns deterministic, machine-readable results for automation.
"""

from __future__ import annotations

import inspect
import json
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Tuple

ErrorKind = Literal["invalid_input", "missing_config", "external_failure", "internal_error"]
BackendKind = Literal["thomas_tool", "webbrowser", "noop"]


@dataclass(frozen=True)
class BrowserOpenError:
    kind: ErrorKind
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "message": self.message, "details": dict(self.details)}


@dataclass(frozen=True)
class BrowserOpenRequest:
    """Input contract for the browser route."""

    url: str | None = None
    config_path: str | None = None
    timeout_s: float | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class BrowserOpenResult:
    """Output contract for the browser route."""

    ok: bool
    url: str | None
    opened: bool
    backend: BackendKind
    message: str
    error: BrowserOpenError | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "url": self.url,
            "opened": self.opened,
            "backend": self.backend,
            "message": self.message,
            "error": None if self.error is None else self.error.to_dict(),
            "meta": dict(self.meta),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


class BrowserOpenException(Exception):
    def __init__(self, error: BrowserOpenError):
        super().__init__(error.message)
        self.error = error


_ALLOWED_URL_SCHEMES = {"http", "https"}


def _load_config(config_path: str | None) -> dict[str, Any]:
    if config_path is None or str(config_path).strip() == "":
        return {}

    path = Path(str(config_path)).expanduser()
    if not path.exists():
        raise BrowserOpenException(
            BrowserOpenError(
                kind="missing_config",
                message="config file not found",
                details={"config_path": str(path)},
            )
        )
    if path.is_dir():
        raise BrowserOpenException(
            BrowserOpenError(
                kind="invalid_input",
                message="config path points to a directory",
                details={"config_path": str(path)},
            )
        )

    if path.suffix.lower() == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            raise BrowserOpenException(
                BrowserOpenError(
                    kind="invalid_input",
                    message="config file is not valid JSON",
                    details={"config_path": str(path), "error": type(e).__name__},
                )
            )
        if not isinstance(data, dict):
            raise BrowserOpenException(
                BrowserOpenError(
                    kind="invalid_input",
                    message="config JSON must be an object",
                    details={"config_path": str(path), "json_type": type(data).__name__},
                )
            )
        return data

    # Unknown config types are accepted but treated as opaque.
    return {"config_path": str(path)}


def _normalize_url(url: str | None) -> str | None:
    if url is None:
        return None
    if not isinstance(url, str):
        raise BrowserOpenException(
            BrowserOpenError(
                kind="invalid_input",
                message="url must be a string",
                details={"received_type": type(url).__name__},
            )
        )

    raw = url.strip()
    if raw == "":
        return None

    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme == "":
        candidate = f"https://{raw}"
        parsed2 = urllib.parse.urlparse(candidate)
        if parsed2.scheme in _ALLOWED_URL_SCHEMES and parsed2.netloc:
            return candidate

    if parsed.scheme not in _ALLOWED_URL_SCHEMES:
        raise BrowserOpenException(
            BrowserOpenError(
                kind="invalid_input",
                message=f"unsupported url scheme: {parsed.scheme or '(none)'}",
                details={"url": raw, "allowed_schemes": sorted(_ALLOWED_URL_SCHEMES)},
            )
        )
    if not parsed.netloc:
        raise BrowserOpenException(
            BrowserOpenError(
                kind="invalid_input",
                message="url must include a host",
                details={"url": raw},
            )
        )
    return raw


def _interpret_open_return(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        for key in ("ok", "success", "opened"):
            v = value.get(key)
            if isinstance(v, bool):
                return v
        return True
    for attr in ("ok", "success", "opened"):
        if hasattr(value, attr):
            v = getattr(value, attr)
            if isinstance(v, bool):
                return v
    return True


def _call_open_callable(fn: Any, url: str, config: dict[str, Any], timeout_s: float | None) -> Any:
    sig = inspect.signature(fn)
    kwargs: dict[str, Any] = {}

    # Best-effort keyword mapping (only if the callable supports it).
    if "config" in sig.parameters:
        kwargs["config"] = config
    elif "settings" in sig.parameters:
        kwargs["settings"] = config
    elif "browser_config" in sig.parameters:
        kwargs["browser_config"] = config

    if timeout_s is not None:
        if "timeout_s" in sig.parameters:
            kwargs["timeout_s"] = timeout_s
        elif "timeout" in sig.parameters:
            kwargs["timeout"] = timeout_s
        elif "timeout_seconds" in sig.parameters:
            kwargs["timeout_seconds"] = timeout_s

    # Prefer positional URL when possible.
    try:
        return fn(url, **kwargs)
    except TypeError:
        # Fall back to keyword URL if we can find a likely parameter name.
        for name in ("url", "href", "target", "uri"):
            if name in sig.parameters:
                kwargs[name] = url
                return fn(**kwargs)
        raise


def _try_open_with_thomas_tool(
    url: str, config: dict[str, Any], timeout_s: float | None
) -> tuple[bool | None, dict[str, Any]]:
    try:
        import thomas.tools.browser as tb  # type: ignore
    except Exception as e:
        return None, {"tool_import_error": type(e).__name__}

    candidates = ("open_url", "open", "launch", "browse", "open_in_browser")
    callables = [name for name in candidates if callable(getattr(tb, name, None))]
    if not callables:
        return None, {"tool_available": True, "tool_callable": None}

    for name in callables:
        fn = getattr(tb, name, None)
        if not callable(fn):
            continue
        try:
            raw = _call_open_callable(fn, url, config, timeout_s)
            opened = _interpret_open_return(raw)
            return opened, {"tool_callable": name, "tool_return_type": type(raw).__name__}
        except TypeError:
            # Signature mismatch; try next candidate.
            continue
        except Exception as e:
            raise BrowserOpenException(
                BrowserOpenError(
                    kind="external_failure",
                    message="browser tool failed",
                    details={"tool_callable": name, "error": type(e).__name__},
                )
            )

    return None, {"tool_available": True, "tool_callable": callables, "note": "no compatible signature"}


def _open_with_webbrowser(url: str) -> bool:
    try:
        return bool(webbrowser.open(url, new=2, autoraise=True))
    except Exception as e:
        raise BrowserOpenException(
            BrowserOpenError(
                kind="external_failure",
                message="failed to open system browser",
                details={"error": type(e).__name__, "url": url},
            )
        )


def open_url(request: BrowserOpenRequest) -> BrowserOpenResult:
    """Open a URL with deterministic output and error handling."""

    backend_meta: dict[str, Any] = {}
    normalized_url: str | None = None
    config: dict[str, Any] = {}

    try:
        config = _load_config(request.config_path)
        normalized_url = _normalize_url(request.url)
        if normalized_url is None:
            raise BrowserOpenException(
                BrowserOpenError(kind="invalid_input", message="url is required", details={})
            )

        if request.dry_run:
            return BrowserOpenResult(
                ok=True,
                url=normalized_url,
                opened=False,
                backend="noop",
                message="dry run: validated request",
                meta={"dry_run": True, "config": config},
            )

        opened_tool, tool_meta = _try_open_with_thomas_tool(normalized_url, config, request.timeout_s)
        if opened_tool is not None:
            backend_meta = {"backend": "thomas_tool", **tool_meta}
            if not opened_tool:
                raise BrowserOpenException(
                    BrowserOpenError(
                        kind="external_failure",
                        message="browser tool did not accept the request",
                        details={"url": normalized_url, **tool_meta},
                    )
                )
            return BrowserOpenResult(
                ok=True,
                url=normalized_url,
                opened=True,
                backend="thomas_tool",
                message="opened url with browser tool",
                meta={"config": config, **backend_meta},
            )

        opened = _open_with_webbrowser(normalized_url)
        backend_meta = {"backend": "webbrowser"}
        if not opened:
            raise BrowserOpenException(
                BrowserOpenError(
                    kind="external_failure",
                    message="system browser did not accept the request",
                    details={"url": normalized_url},
                )
            )
        return BrowserOpenResult(
            ok=True,
            url=normalized_url,
            opened=True,
            backend="webbrowser",
            message="opened url in system browser",
            meta={"config": config, **backend_meta},
        )

    except BrowserOpenException as e:
        return BrowserOpenResult(
            ok=False,
            url=normalized_url if normalized_url is not None else request.url,
            opened=False,
            backend="noop",
            message=e.error.message,
            error=e.error,
            meta={"config": config, **backend_meta} if (config or backend_meta) else {},
        )
    except Exception as e:  # pragma: no cover
        err = BrowserOpenError(
            kind="internal_error",
            message="unexpected error",
            details={"error": type(e).__name__},
        )
        return BrowserOpenResult(
            ok=False,
            url=normalized_url if normalized_url is not None else request.url,
            opened=False,
            backend="noop",
            message=err.message,
            error=err,
            meta={"config": config, **backend_meta} if (config or backend_meta) else {},
        )


def result_json_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ThomasBrowserOpenResult",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "ok": {"type": "boolean"},
            "url": {"type": ["string", "null"]},
            "opened": {"type": "boolean"},
            "backend": {"type": "string", "enum": ["thomas_tool", "webbrowser", "noop"]},
            "message": {"type": "string"},
            "meta": {"type": "object"},
            "error": {
                "type": ["object", "null"],
                "additionalProperties": False,
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["invalid_input", "missing_config", "external_failure", "internal_error"],
                    },
                    "message": {"type": "string"},
                    "details": {"type": "object"},
                },
                "required": ["kind", "message", "details"],
            },
        },
        "required": ["ok", "url", "opened", "backend", "message", "meta", "error"],
    }
