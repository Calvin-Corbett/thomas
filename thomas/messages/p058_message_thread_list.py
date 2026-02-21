"""Thomas-native message thread listing (P058).

This module implements listing message threads in a backend-agnostic way.

Key properties
- Clear input/output contracts via dataclasses.
- Deterministic errors for invalid input, missing configuration, and
  external/backend failures.
- Supports a machine-readable dict-in/dict-out entrypoint (`run`) for
  automation.

Backend resolution
- If a local JSONL message store path is configured, threads are derived from
  that store.
- Otherwise, the module attempts best-effort adaptation to any existing Thomas
  messaging backend.
- If nothing is configured/resolvable, a config error is raised.

Local JSONL store format
Each line must be a JSON object. Required fields:
- thread_id: str

Optional fields used for richer summaries:
- channel_id: str
- title: str
- timestamp: ISO-8601 string (with optional trailing 'Z')
- sender: str
- participants: list[str]
- archived: bool
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol, Sequence, cast

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class MessageThreadListError(Exception):
    """Base error for message thread listing."""

    code: str = "error"

    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        # Force a plain dict to keep JSON output stable and serializable.
        self.details: dict[str, Any] = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


class MessageThreadListInvalidInput(MessageThreadListError):
    code = "invalid_input"


class MessageThreadListConfigError(MessageThreadListError):
    code = "missing_config"


class MessageThreadListExternalError(MessageThreadListError):
    code = "external_failure"


@dataclass(frozen=True)
class MessageThreadListRequest:
    """Input contract for listing threads."""

    channel_id: str | None = None
    limit: int = DEFAULT_LIMIT
    cursor: str | None = None
    include_archived: bool = False

    def validate(self) -> None:
        if self.channel_id is not None and not isinstance(self.channel_id, str):
            raise MessageThreadListInvalidInput(
                "channel_id must be a string",
                details={"field": "channel_id"},
            )

        if self.channel_id is not None and not self.channel_id.strip():
            raise MessageThreadListInvalidInput(
                "channel_id must be a non-empty string",
                details={"field": "channel_id"},
            )

        if not isinstance(self.limit, int):
            raise MessageThreadListInvalidInput(
                "limit must be an integer",
                details={"field": "limit"},
            )

        if self.limit < 1 or self.limit > MAX_LIMIT:
            raise MessageThreadListInvalidInput(
                f"limit must be between 1 and {MAX_LIMIT}",
                details={"field": "limit", "min": 1, "max": MAX_LIMIT},
            )

        if self.cursor is not None:
            if not isinstance(self.cursor, str):
                raise MessageThreadListInvalidInput(
                    "cursor must be a string",
                    details={"field": "cursor"},
                )
            if not self.cursor.strip():
                raise MessageThreadListInvalidInput(
                    "cursor must be a non-empty string when provided",
                    details={"field": "cursor"},
                )

        if not isinstance(self.include_archived, bool):
            # Keep it strict for automation.
            raise MessageThreadListInvalidInput(
                "include_archived must be a boolean",
                details={"field": "include_archived"},
            )


@dataclass(frozen=True)
class MessageThreadSummary:
    """Output contract for a single thread summary."""

    thread_id: str
    channel_id: str | None = None
    title: str | None = None
    last_message_at: datetime | None = None
    message_count: int = 0
    participants: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "channel_id": self.channel_id,
            "title": self.title,
            "last_message_at": self.last_message_at.isoformat() if self.last_message_at else None,
            "message_count": self.message_count,
            "participants": list(self.participants),
        }


@dataclass(frozen=True)
class MessageThreadListResponse:
    """Output contract for listing threads."""

    threads: list[MessageThreadSummary] = field(default_factory=list)
    next_cursor: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "threads": [t.to_dict() for t in self.threads],
            "next_cursor": self.next_cursor,
        }


class MessageThreadBackend(Protocol):
    def list_threads(self, request: MessageThreadListRequest) -> MessageThreadListResponse:
        ...


def list_message_threads(
    request: MessageThreadListRequest,
    *,
    backend: MessageThreadBackend | None = None,
    config: Mapping[str, Any] | None = None,
) -> MessageThreadListResponse:
    """List message threads."""

    request.validate()

    resolved_backend = backend or _resolve_backend(config)

    try:
        raw = resolved_backend.list_threads(request)
    except MessageThreadListError:
        raise
    except Exception as exc:  # pragma: no cover
        raise MessageThreadListExternalError(
            "Message thread backend failure",
            details={"cause": type(exc).__name__},
        ) from exc

    if isinstance(raw, MessageThreadListResponse):
        return raw

    return _coerce_response(raw)


def _coerce_response(raw: Any) -> MessageThreadListResponse:
    if isinstance(raw, MessageThreadListResponse):
        return raw

    if isinstance(raw, Mapping):
        threads_raw = raw.get("threads") or []
        next_cursor = raw.get("next_cursor")
        return MessageThreadListResponse(
            threads=[_coerce_thread(t) for t in threads_raw],
            next_cursor=cast(Optional[str], next_cursor),
        )

    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        return MessageThreadListResponse(threads=[_coerce_thread(t) for t in raw], next_cursor=None)

    raise MessageThreadListExternalError(
        "Backend returned an unsupported response type",
        details={"type": type(raw).__name__},
    )


def _coerce_thread(raw: Any) -> MessageThreadSummary:
    if isinstance(raw, MessageThreadSummary):
        return raw

    if not isinstance(raw, Mapping):
        raise MessageThreadListExternalError(
            "Backend returned a thread with an unsupported type",
            details={"type": type(raw).__name__},
        )

    thread_id = raw.get("thread_id")
    if not isinstance(thread_id, str) or not thread_id.strip():
        raise MessageThreadListExternalError(
            "Backend returned a thread missing thread_id",
            details={"thread_id": thread_id},
        )

    # last_message_at may be datetime or ISO-8601 string.
    last_message_at = raw.get("last_message_at")
    parsed_dt: datetime | None
    if isinstance(last_message_at, datetime):
        parsed_dt = _normalize_dt(last_message_at)
    elif isinstance(last_message_at, str):
        parsed_dt = _parse_iso8601(last_message_at)
    else:
        parsed_dt = None

    participants = raw.get("participants")
    participants_list: list[str]
    if isinstance(participants, list):
        participants_list = [str(p).strip() for p in participants if str(p).strip()]
    else:
        participants_list = []

    message_count_raw = raw.get("message_count")
    try:
        message_count = int(message_count_raw) if message_count_raw is not None else 0
    except Exception:
        message_count = 0

    return MessageThreadSummary(
        thread_id=thread_id,
        channel_id=cast(Optional[str], raw.get("channel_id")),
        title=cast(Optional[str], raw.get("title")),
        last_message_at=parsed_dt,
        message_count=max(message_count, 0),
        participants=participants_list,
    )


def _normalize_dt(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_iso8601(value: str) -> datetime | None:
    v = value.strip()
    if not v:
        return None

    # Support trailing Z.
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None

    return _normalize_dt(dt)


class JsonlMessageStoreBackend:
    """Backend that derives thread summaries from a JSONL message store."""

    def __init__(self, store_path: str | Path):
        self._path = Path(store_path)

    def list_threads(self, request: MessageThreadListRequest) -> MessageThreadListResponse:
        if not self._path.exists():
            raise MessageThreadListConfigError(
                "message store path does not exist",
                details={"path": str(self._path)},
            )

        try:
            fh = self._path.open("r", encoding="utf-8")
        except OSError as exc:
            raise MessageThreadListExternalError(
                "failed to open message store",
                details={"path": str(self._path), "cause": type(exc).__name__},
            ) from exc

        with fh:
            summaries = _summaries_from_jsonl_stream(fh, request)

        return _paginate_summaries(summaries, request)


def _summaries_from_jsonl_stream(
    fh: Any,
    request: MessageThreadListRequest,
) -> list[MessageThreadSummary]:
    """Aggregate thread summaries from a JSONL file-like object."""

    by_thread: dict[str, dict[str, Any]] = {}

    for line_no, line in enumerate(fh, start=1):
        if not line.strip():
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MessageThreadListExternalError(
                "invalid JSON in message store",
                details={"path": getattr(fh, "name", None), "line": line_no},
            ) from exc

        if not isinstance(msg, Mapping):
            continue

        thread_id = msg.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id.strip():
            continue

        channel_id = msg.get("channel_id")
        if request.channel_id is not None and channel_id != request.channel_id:
            continue

        archived = bool(msg.get("archived", False))

        bucket = by_thread.setdefault(
            thread_id,
            {
                "thread_id": thread_id,
                "channel_id": channel_id if isinstance(channel_id, str) else None,
                "title": msg.get("title") if isinstance(msg.get("title"), str) else None,
                "message_count": 0,
                "participants": set(),
                "last_message_at": None,
                "archived": archived,
            },
        )

        bucket["message_count"] += 1
        if archived:
            bucket["archived"] = True

        sender = msg.get("sender")
        if isinstance(sender, str) and sender.strip():
            bucket["participants"].add(sender)

        participants = msg.get("participants")
        if isinstance(participants, list):
            for p in participants:
                ps = str(p).strip()
                if ps:
                    bucket["participants"].add(ps)

        ts = msg.get("timestamp")
        dt = _parse_iso8601(ts) if isinstance(ts, str) else None
        if dt is not None:
            current = cast(Optional[datetime], bucket["last_message_at"])
            if current is None or dt > current:
                bucket["last_message_at"] = dt

    summaries: list[MessageThreadSummary] = []
    for data in by_thread.values():
        if not request.include_archived and bool(data.get("archived", False)):
            continue

        participants_sorted = sorted(cast(set[str], data["participants"]))
        summaries.append(
            MessageThreadSummary(
                thread_id=cast(str, data["thread_id"]),
                channel_id=cast(Optional[str], data.get("channel_id")),
                title=cast(Optional[str], data.get("title")),
                last_message_at=cast(Optional[datetime], data.get("last_message_at")),
                message_count=int(cast(int, data.get("message_count", 0))),
                participants=participants_sorted,
            )
        )

    # Sort newest first; stable tie-break by thread_id.
    min_dt = datetime.min.replace(tzinfo=timezone.utc)
    summaries.sort(
        key=lambda t: (
            t.last_message_at or min_dt,
            t.thread_id,
        ),
        reverse=True,
    )

    return summaries


def _paginate_summaries(
    summaries: Sequence[MessageThreadSummary],
    request: MessageThreadListRequest,
) -> MessageThreadListResponse:
    offset = 0
    if request.cursor is not None:
        try:
            offset = int(request.cursor)
        except ValueError as exc:
            raise MessageThreadListInvalidInput(
                "cursor must be an integer offset",
                details={"field": "cursor"},
            ) from exc
        if offset < 0:
            offset = 0

    end = offset + request.limit
    page = list(summaries[offset:end])

    next_cursor: str | None = None
    if end < len(summaries):
        next_cursor = str(end)

    return MessageThreadListResponse(threads=page, next_cursor=next_cursor)


def _resolve_backend(config: Mapping[str, Any] | None) -> MessageThreadBackend:
    backend_from_config = _get_backend_from_config(config)
    if backend_from_config is not None:
        return backend_from_config

    store_path = _get_store_path(config)
    if store_path is not None:
        return JsonlMessageStoreBackend(store_path)

    adapted = _try_adapt_existing_backend(config)
    if adapted is not None:
        return adapted

    raise MessageThreadListConfigError(
        "No message thread backend is configured",
        details={
            "hint": (
                "Provide a JSONL message store path via THOMAS_MESSAGE_STORE_PATH "
                "(or config['message_store_path']), or configure a Thomas messaging backend."
            )
        },
    )


def _get_backend_from_config(config: Mapping[str, Any] | None) -> MessageThreadBackend | None:
    if config is None:
        return None

    for key in (
        "message_thread_backend",
        "message_backend",
        "messages_backend",
        "backend",
    ):
        candidate = config.get(key)
        wrapped = _wrap_backend_obj(candidate)
        if wrapped is not None:
            return wrapped

    return None


def _get_store_path(config: Mapping[str, Any] | None) -> str | None:
    if config is not None:
        for key in (
            "message_store_path",
            "messages_store_path",
            "message_thread_store_path",
            "message_store",
        ):
            value = config.get(key)
            if isinstance(value, str) and value.strip():
                return value

    for env_key in (
        "THOMAS_MESSAGE_STORE_PATH",
        "THOMAS_MESSAGES_STORE_PATH",
        "THOMAS_MESSAGE_THREAD_STORE_PATH",
    ):
        v = os.getenv(env_key)
        if v and v.strip():
            return v

    return None


def _try_adapt_existing_backend(config: Mapping[str, Any] | None) -> MessageThreadBackend | None:
    """Best-effort adaptation to an existing Thomas messaging backend."""

    candidates: list[tuple[str, str]] = [
        ("thomas.messages", "get_thread_backend"),
        ("thomas.messages", "get_backend"),
        ("thomas.messages.backend", "get_backend"),
        ("thomas.messages.client", "MessagesClient"),
        ("thomas.messages.service", "MessagesService"),
    ]

    for module_name, attr_name in candidates:
        try:
            mod = importlib.import_module(module_name)
        except Exception:
            continue

        attr = getattr(mod, attr_name, None)
        if attr is None:
            continue

        # Factory functions
        if callable(attr) and attr_name.startswith("get_"):
            try:
                maybe_backend = attr(config) if config is not None else attr()
            except TypeError:
                try:
                    maybe_backend = attr()
                except Exception:
                    continue
            except Exception:
                continue

            wrapped = _wrap_backend_obj(maybe_backend)
            if wrapped is not None:
                return wrapped

        # Classes
        if isinstance(attr, type):
            try:
                instance = attr(config=config) if config is not None else attr()
            except TypeError:
                try:
                    instance = attr(config) if config is not None else attr()
                except Exception:
                    continue
            except Exception:
                continue

            wrapped = _wrap_backend_obj(instance)
            if wrapped is not None:
                return wrapped

    return None


def _wrap_backend_obj(obj: Any) -> MessageThreadBackend | None:
    if obj is None:
        return None

    if hasattr(obj, "list_threads") and callable(getattr(obj, "list_threads")):
        return cast(MessageThreadBackend, obj)

    # Alternate method names
    for method_name in (
        "list_message_threads",
        "thread_list",
        "threads_list",
        "listThreads",
    ):
        method = getattr(obj, method_name, None)
        if callable(method):
            return _CallableBackendAdapter(method)

    return None


class _CallableBackendAdapter:
    def __init__(self, fn: Any):
        self._fn = fn

    def list_threads(self, request: MessageThreadListRequest) -> MessageThreadListResponse:
        try:
            raw = self._fn(
                channel_id=request.channel_id,
                limit=request.limit,
                cursor=request.cursor,
                include_archived=request.include_archived,
            )
        except TypeError:
            raw = self._fn(
                {
                    "channel_id": request.channel_id,
                    "limit": request.limit,
                    "cursor": request.cursor,
                    "include_archived": request.include_archived,
                }
            )

        return _coerce_response(raw)


def run(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Automation-friendly entrypoint (dict in, dict out)."""

    data: Mapping[str, Any] = payload or {}

    channel_id = data.get("channel_id", data.get("channel"))

    limit_raw = data.get("limit", DEFAULT_LIMIT)
    try:
        limit = int(limit_raw)
    except Exception:
        limit = limit_raw  # validated later

    req = MessageThreadListRequest(
        channel_id=cast(Optional[str], channel_id),
        limit=cast(int, limit),
        cursor=cast(Optional[str], data.get("cursor")),
        include_archived=bool(data.get("include_archived", False)),
    )

    config_raw = data.get("config")
    config = cast(Optional[Mapping[str, Any]], config_raw) if isinstance(config_raw, Mapping) else None

    try:
        resp = list_message_threads(req, config=config)
    except MessageThreadListError as exc:
        return {"ok": False, **exc.to_dict()}

    return {"ok": True, **resp.to_dict()}
