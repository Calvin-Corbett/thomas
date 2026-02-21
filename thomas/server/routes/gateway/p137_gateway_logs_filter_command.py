"""Gateway logs filter command (server route).

Implements a deterministic, Thomas-native gateway route for filtering gateway logs.

Key goals:
- Deterministic JSON errors (stable `code` + `message`)
- No external process execution
- Machine-readable output (route always returns JSON)
- Efficient "newest_first" behavior without reading entire file into memory
- Tail-mode: if no filters are provided, return the last N lines efficiently
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import json
import os
import re
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Mapping, Optional, Sequence, TypedDict, cast

from aiohttp import web


# ----------------------------- Contracts -----------------------------

class GatewayLogMatch(TypedDict, total=False):
    line_number: int
    text: str
    timestamp: str
    level: str
    json: Dict[str, Any]


class GatewayLogsFilterResponse(TypedDict):
    ok: bool
    matches: List[GatewayLogMatch]
    scanned_lines: int
    truncated: bool


class GatewayLogsFilterErrorBody(TypedDict):
    code: str
    message: str
    fields: Dict[str, str]


class GatewayLogsFilterFailure(TypedDict):
    ok: bool
    error: GatewayLogsFilterErrorBody


class GatewayLogsFilterRequest(TypedDict, total=False):
    # Filtering options
    contains: str
    regex: str
    ignore_case: bool
    levels: List[str]
    after: str  # ISO 8601
    before: str  # ISO 8601

    # Output controls
    limit: int
    newest_first: bool

    # Optional override for tests/internal tooling.
    # This is disabled unless explicitly allowed by config/env.
    path: str


# ----------------------------- Errors -----------------------------

class GatewayLogsFilterError(Exception):
    """Deterministic, user-facing error for the gateway logs filter API."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        http_status: int = 400,
        fields: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.fields = fields or {}

    def to_response(self) -> web.Response:
        return web.json_response(
            {"ok": False, "error": {"code": self.code, "message": self.message, "fields": self.fields}},
            status=self.http_status,
        )


# ----------------------------- Internal model -----------------------------

@dataclasses.dataclass(frozen=True)
class _ParsedRequest:
    contains: Optional[str]
    regex: Optional[re.Pattern[str]]
    ignore_case: bool
    levels: Optional[Sequence[str]]
    after: Optional[_dt.datetime]
    before: Optional[_dt.datetime]
    limit: int
    newest_first: bool
    path_override: Optional[Path]


_DEFAULT_LIMIT = 200
_MAX_LIMIT = 10_000
_TAIL_BLOCK_BYTES = 8192


# ----------------------------- Helpers -----------------------------

def _parse_iso_datetime(value: str, *, field: str) -> _dt.datetime:
    raw = value.strip()
    if not raw:
        raise GatewayLogsFilterError(
            code="INVALID_INPUT",
            message="Invalid request.",
            fields={field: "must be a non-empty ISO 8601 timestamp"},
        )
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    try:
        dt = _dt.datetime.fromisoformat(raw)
    except ValueError:
        raise GatewayLogsFilterError(
            code="INVALID_INPUT",
            message="Invalid request.",
            fields={field: f"must be an ISO 8601 timestamp (got {value!r})"},
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt


def _extract_timestamp_from_line(line: str) -> Optional[_dt.datetime]:
    stripped = line.strip()
    if not stripped:
        return None

    # JSON line
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            obj = json.loads(stripped)
        except Exception:
            obj = None
        if isinstance(obj, dict):
            for key in ("timestamp", "time", "ts"):
                v = obj.get(key)
                if isinstance(v, str):
                    try:
                        return _parse_iso_datetime(v, field=key)
                    except GatewayLogsFilterError:
                        return None

    # Prefix ISO timestamp
    m = re.match(
        r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)",
        stripped,
    )
    if not m:
        return None
    try:
        return _parse_iso_datetime(m.group(1), field="timestamp")
    except GatewayLogsFilterError:
        return None


def _extract_level_from_line(line: str) -> Optional[str]:
    # JSON line might provide a level field.
    stripped = line.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict) and isinstance(obj.get("level"), str):
                lvl = cast(str, obj["level"]).upper()
                if lvl == "WARNING":
                    return "WARN"
                return lvl
        except Exception:
            pass

    m = re.search(r"\b(DEBUG|INFO|WARN|WARNING|ERROR|CRITICAL)\b", line)
    if not m:
        return None
    lvl = m.group(1)
    return "WARN" if lvl == "WARNING" else lvl


def _resolve_config_mapping(app: web.Application) -> Mapping[str, Any]:
    cfg = app.get("config") or app.get("settings") or app.get("cfg")
    if isinstance(cfg, Mapping):
        return cfg
    if cfg is not None:
        return cast(Mapping[str, Any], getattr(cfg, "__dict__", {}))
    return {}


def _is_path_override_allowed(request: web.Request) -> bool:
    if os.getenv("THOMAS_ALLOW_LOG_PATH_OVERRIDE", "").strip() in ("1", "true", "TRUE", "yes", "YES"):
        return True
    cfg = _resolve_config_mapping(request.app)
    v = cfg.get("gateway_logs_allow_path_override")
    return bool(v)


def _resolve_log_path(request: web.Request, parsed: _ParsedRequest) -> Path:
    if parsed.path_override is not None:
        if not _is_path_override_allowed(request):
            raise GatewayLogsFilterError(
                code="INVALID_INPUT",
                message="Invalid request.",
                fields={"path": "path override is not allowed"},
            )
        return parsed.path_override

    env_path = os.getenv("THOMAS_GATEWAY_LOG_PATH") or os.getenv("THOMAS_LOG_PATH")
    if env_path:
        return Path(env_path)

    cfg = _resolve_config_mapping(request.app)
    for key in (
        "gateway_log_path",
        "gateway.logs.path",
        "gateway.logs_path",
        "gateway.logs.file",
        "gateway_log_file",
        "gateway_logs_path",
        "logs.gateway.path",
    ):
        v = cfg.get(key)
        if isinstance(v, str) and v.strip():
            return Path(v)

    raise GatewayLogsFilterError(
        code="MISSING_CONFIG",
        message="Gateway log path is not configured.",
        http_status=500,
    )


def parse_filter_request(payload: Mapping[str, Any]) -> _ParsedRequest:
    fields: Dict[str, str] = {}

    contains = payload.get("contains")
    if contains is not None and not isinstance(contains, str):
        fields["contains"] = "must be a string"

    regex_text = payload.get("regex")
    ignore_case = bool(payload.get("ignore_case", False))
    regex: Optional[re.Pattern[str]] = None
    if regex_text is not None and not isinstance(regex_text, str):
        fields["regex"] = "must be a string"
    elif isinstance(regex_text, str):
        flags = re.IGNORECASE if ignore_case else 0
        try:
            regex = re.compile(regex_text, flags=flags)
        except re.error as e:
            fields["regex"] = f"invalid regex: {e.msg}"

    levels_val = payload.get("levels")
    levels: Optional[Sequence[str]] = None
    if levels_val is not None:
        if isinstance(levels_val, str):
            levels = [levels_val]
        elif isinstance(levels_val, list) and all(isinstance(x, str) for x in levels_val):
            levels = cast(List[str], levels_val)
        else:
            fields["levels"] = "must be a string or list of strings"

    after_val = payload.get("after")
    after: Optional[_dt.datetime] = None
    if after_val is not None:
        if not isinstance(after_val, str):
            fields["after"] = "must be a string timestamp"
        else:
            try:
                after = _parse_iso_datetime(after_val, field="after")
            except GatewayLogsFilterError as e:
                fields["after"] = e.fields.get("after", "invalid timestamp")

    before_val = payload.get("before")
    before: Optional[_dt.datetime] = None
    if before_val is not None:
        if not isinstance(before_val, str):
            fields["before"] = "must be a string timestamp"
        else:
            try:
                before = _parse_iso_datetime(before_val, field="before")
            except GatewayLogsFilterError as e:
                fields["before"] = e.fields.get("before", "invalid timestamp")

    limit_val = payload.get("limit", _DEFAULT_LIMIT)
    if not isinstance(limit_val, int):
        fields["limit"] = "must be an integer"
        limit_val = _DEFAULT_LIMIT
    else:
        if limit_val <= 0:
            fields["limit"] = "must be > 0"
        elif limit_val > _MAX_LIMIT:
            fields["limit"] = f"must be <= {_MAX_LIMIT}"

    newest_first = bool(payload.get("newest_first", False))

    path_val = payload.get("path")
    path_override: Optional[Path] = None
    if path_val is not None:
        if not isinstance(path_val, str) or not path_val.strip():
            fields["path"] = "must be a non-empty string"
        else:
            path_override = Path(path_val)

    if fields:
        raise GatewayLogsFilterError(code="INVALID_INPUT", message="Invalid request.", fields=fields)

    return _ParsedRequest(
        contains=cast(Optional[str], contains),
        regex=regex,
        ignore_case=ignore_case,
        levels=levels,
        after=after,
        before=before,
        limit=cast(int, limit_val),
        newest_first=newest_first,
        path_override=path_override,
    )


def _tail_lines(path: Path, n: int) -> List[str]:
    # Efficiently read the last n lines of a (potentially large) file.
    if n <= 0:
        return []
    with path.open("rb") as f:
        f.seek(0, 2)
        end = f.tell()
        if end == 0:
            return []
        buf = b""
        pos = end
        while pos > 0 and buf.count(b"\n") <= n:
            read_size = _TAIL_BLOCK_BYTES if pos >= _TAIL_BLOCK_BYTES else pos
            pos -= read_size
            f.seek(pos)
            buf = f.read(read_size) + buf
        lines = buf.splitlines()[-n:]
        return [ln.decode("utf-8", errors="replace") for ln in lines]


def _matches_filters(text: str, parsed: _ParsedRequest, *, contains_norm: Optional[str], levels_norm: Optional[List[str]]) -> bool:
    if not text:
        return False

    if contains_norm is not None:
        hay = text.lower() if parsed.ignore_case else text
        if contains_norm not in hay:
            return False

    if parsed.regex is not None:
        if parsed.regex.search(text) is None:
            return False

    if levels_norm is not None:
        lvl = _extract_level_from_line(text)
        if lvl is None or lvl.upper() not in levels_norm:
            return False

    if parsed.after is not None or parsed.before is not None:
        ts = _extract_timestamp_from_line(text)
        if ts is None:
            return False
        if parsed.after is not None and ts < parsed.after:
            return False
        if parsed.before is not None and ts > parsed.before:
            return False

    return True


def filter_log_file(log_path: Path, parsed: _ParsedRequest) -> GatewayLogsFilterResponse:
    if not log_path.exists():
        raise GatewayLogsFilterError(
            code="LOG_READ_FAILED",
            message=f"Gateway log file does not exist: {str(log_path)}",
            http_status=500,
        )
    if not log_path.is_file():
        raise GatewayLogsFilterError(
            code="LOG_READ_FAILED",
            message=f"Gateway log path is not a file: {str(log_path)}",
            http_status=500,
        )

    contains_norm: Optional[str] = None
    if parsed.contains is not None:
        contains_norm = parsed.contains.lower() if parsed.ignore_case else parsed.contains

    levels_norm: Optional[List[str]] = None
    if parsed.levels is not None:
        levels_norm = [lvl.upper() for lvl in parsed.levels]

    # Tail-mode: no filters besides limit/newest_first -> return last N lines
    has_any_filter = any(
        [
            parsed.contains is not None,
            parsed.regex is not None,
            parsed.levels is not None,
            parsed.after is not None,
            parsed.before is not None,
        ]
    )
    if not has_any_filter:
        lines = _tail_lines(log_path, parsed.limit)
        matches: List[GatewayLogMatch] = []
        # We don't know exact line numbers without scanning; omit for tail-mode.
        for t in lines:
            m: GatewayLogMatch = {"text": t}
            ts = _extract_timestamp_from_line(t)
            if ts is not None:
                m["timestamp"] = ts.isoformat()
            lvl = _extract_level_from_line(t)
            if lvl is not None:
                m["level"] = lvl
            st = t.strip()
            if st.startswith("{") and st.endswith("}"):
                try:
                    obj = json.loads(st)
                    if isinstance(obj, dict):
                        m["json"] = cast(Dict[str, Any], obj)
                except Exception:
                    pass
            matches.append(m)
        if parsed.newest_first:
            matches = list(reversed(matches))
        return {"ok": True, "matches": matches, "scanned_lines": len(lines), "truncated": False}

    # Filter-mode
    scanned = 0
    truncated = False
    if parsed.newest_first:
        # Keep only the newest `limit` matches using a ring buffer.
        ring: Deque[GatewayLogMatch] = deque(maxlen=parsed.limit)
        total_matches = 0
        try:
            with log_path.open("r", encoding="utf-8", errors="replace") as f:
                for idx, line in enumerate(f, start=1):
                    scanned += 1
                    text = line.rstrip("\n")
                    if not _matches_filters(text, parsed, contains_norm=contains_norm, levels_norm=levels_norm):
                        continue
                    total_matches += 1
                    match: GatewayLogMatch = {"line_number": idx, "text": text}
                    ts2 = _extract_timestamp_from_line(text)
                    if ts2 is not None:
                        match["timestamp"] = ts2.isoformat()
                    lvl2 = _extract_level_from_line(text)
                    if lvl2 is not None:
                        match["level"] = lvl2
                    st = text.strip()
                    if st.startswith("{") and st.endswith("}"):
                        try:
                            obj = json.loads(st)
                            if isinstance(obj, dict):
                                match["json"] = cast(Dict[str, Any], obj)
                        except Exception:
                            pass
                    ring.append(match)
        except Exception as e:
            raise GatewayLogsFilterError(
                code="LOG_READ_FAILED",
                message=f"Failed to read gateway log file: {e.__class__.__name__}",
                http_status=500,
            ) from e

        truncated = total_matches > parsed.limit
        matches = list(reversed(list(ring)))  # newest first
        return {"ok": True, "matches": matches, "scanned_lines": scanned, "truncated": truncated}

    # Oldest-first (default): we can early-exit once we hit `limit`.
    matches2: List[GatewayLogMatch] = []
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as f:
            for idx, line in enumerate(f, start=1):
                scanned += 1
                text = line.rstrip("\n")
                if not _matches_filters(text, parsed, contains_norm=contains_norm, levels_norm=levels_norm):
                    continue
                match: GatewayLogMatch = {"line_number": idx, "text": text}
                ts2 = _extract_timestamp_from_line(text)
                if ts2 is not None:
                    match["timestamp"] = ts2.isoformat()
                lvl2 = _extract_level_from_line(text)
                if lvl2 is not None:
                    match["level"] = lvl2
                st = text.strip()
                if st.startswith("{") and st.endswith("}"):
                    try:
                        obj = json.loads(st)
                        if isinstance(obj, dict):
                            match["json"] = cast(Dict[str, Any], obj)
                    except Exception:
                        pass
                matches2.append(match)
                if len(matches2) >= parsed.limit:
                    truncated = True
                    break
    except Exception as e:
        raise GatewayLogsFilterError(
            code="LOG_READ_FAILED",
            message=f"Failed to read gateway log file: {e.__class__.__name__}",
            http_status=500,
        ) from e

    return {"ok": True, "matches": matches2, "scanned_lines": scanned, "truncated": truncated}


# ----------------------------- Route wiring -----------------------------

ROUTE_METHOD = "POST"
ROUTE_PATH = "/gateway/logs/filter"

routes = web.RouteTableDef()


@routes.post(ROUTE_PATH)
async def gateway_logs_filter_handler(request: web.Request) -> web.Response:
    try:
        try:
            payload = await request.json()
        except Exception:
            raise GatewayLogsFilterError(code="INVALID_INPUT", message="Invalid request.", fields={"body": "must be valid JSON"})

        if not isinstance(payload, dict):
            raise GatewayLogsFilterError(code="INVALID_INPUT", message="Invalid request.", fields={"body": "must be a JSON object"})

        parsed = parse_filter_request(payload)
        log_path = _resolve_log_path(request, parsed)
        resp = filter_log_file(log_path, parsed)
        return web.json_response(resp, status=200)
    except GatewayLogsFilterError as e:
        return e.to_response()
    except Exception as e:
        err = GatewayLogsFilterError(
            code="INTERNAL_ERROR",
            message="Unexpected error.",
            http_status=500,
            fields={"exception": e.__class__.__name__},
        )
        return err.to_response()


def get_routes() -> web.RouteTableDef:
    return routes


ROUTES = routes


def register(app: web.Application) -> None:
    app.add_routes(routes)
