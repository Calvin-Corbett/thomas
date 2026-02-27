"""
P069 - Message event history

Thomas-native capability for recording and querying message lifecycle events.

Design goals:
- Append-only storage for webhook-originated message events.
- Deterministic, automation-friendly errors.
- Minimal dependencies (std-lib only).
- Machine-readable output support (CLI `--json`) via the companion command module.

Storage:
- JSON Lines (.jsonl): one JSON object per line.
- Normalized schema v1 (see `SCHEMA_ID`) with a `raw` payload for forward compatibility.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_ID = "thomas.messages.event.v1"

# -----------------------------
# Public contracts
# -----------------------------


@dataclass(frozen=True, slots=True)
class MessageEvent:
    """A normalized message event.

    - `raw` preserves the original payload for debugging/future schema evolution.
    - `source_path` identifies which store file the event came from (useful when multiple
      files are discovered).
    """

    message_id: str
    event_type: str
    occurred_at: str | None
    raw: Mapping[str, Any]
    source_path: str | None = None


@dataclass(frozen=True, slots=True)
class MessageEventHistoryRequest:
    message_id: str
    limit: int = 200
    store_path: str | None = None  # explicit file path override
    state_dir: str | None = None  # explicit directory override


@dataclass(frozen=True, slots=True)
class MessageEventHistoryResponse:
    message_id: str
    events: Sequence[MessageEvent]
    source_paths: Sequence[str]


# -----------------------------
# Deterministic errors
# -----------------------------


class MessageEventHistoryError(Exception):
    """Base error for this feature.

    All errors carry a deterministic `code` for automation.
    """

    code: str = "messages.event_history.error"

    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": self.details}


class MessageEventHistoryInvalidInputError(MessageEventHistoryError):
    code = "messages.event_history.invalid_input"


class MessageEventHistoryConfigError(MessageEventHistoryError):
    code = "messages.event_history.missing_config"


class MessageEventHistoryExternalFailure(MessageEventHistoryError):
    code = "messages.event_history.external_failure"


# -----------------------------
# Storage defaults + helpers
# -----------------------------

_ENV_STORE_PATH = "THOMAS_MESSAGE_EVENTS_PATH"
_ENV_STATE_DIR = "THOMAS_STATE_DIR"
_ENV_HOME_DIR = "THOMAS_HOME"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat(dt: datetime) -> str:
    # Use Z suffix for UTC for nicer diffs/logs.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _coerce_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            s2 = s.replace("Z", "+00:00") if s.endswith("Z") else s
            dt = datetime.fromisoformat(s2)
            return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (RuntimeError, ValueError, KeyError, AttributeError, TypeError):
            return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (RuntimeError, ValueError, KeyError, AttributeError, TypeError):
            return None
    return None


def _parse_timestamp(value: Any) -> str | None:
    dt = _coerce_dt(value)
    if dt is not None:
        return _isoformat(dt)
    if isinstance(value, str):
        s = value.strip()
        return s or None
    return None


def _default_state_dir() -> Path:
    # Prefer explicit env override, then fall back to ~/.thomas
    env_state = os.environ.get(_ENV_STATE_DIR) or os.environ.get(_ENV_HOME_DIR)
    if env_state:
        return Path(env_state).expanduser()
    return Path.home() / ".thomas"


def _candidate_store_paths(state_dir: Path) -> list[Path]:
    """Return candidate JSONL file paths in priority order."""
    return [
        state_dir / "messages" / "events.jsonl",
        state_dir / "messages" / "message_events.jsonl",
        state_dir / "message_events.jsonl",
        state_dir / "messages_events.jsonl",
        state_dir / "events" / "message_events.jsonl",
        state_dir / "webhooks" / "messages.jsonl",
        state_dir / "webhooks" / "message_events.jsonl",
        state_dir / "webhooks.jsonl",
        state_dir / "webhook_events.jsonl",
        state_dir / "events.jsonl",
    ]


def _resolve_source_paths(*, store_path: str | None, state_dir: str | None) -> list[Path]:
    # Explicit file path override wins.
    if store_path:
        return [Path(store_path).expanduser()]

    # Env override next.
    env_path = os.environ.get(_ENV_STORE_PATH)
    if env_path:
        return [Path(env_path).expanduser()]

    # Otherwise: discover in state dir.
    sd = Path(state_dir).expanduser() if state_dir else _default_state_dir()
    candidates = _candidate_store_paths(sd)

    existing = [p for p in candidates if p.exists() and p.is_file()]
    if existing:
        return existing

    # Also: if there is a webhooks directory with *.jsonl files, include them.
    webhooks_dir = sd / "webhooks"
    if webhooks_dir.exists() and webhooks_dir.is_dir():
        found = sorted([p for p in webhooks_dir.glob("*.jsonl") if p.is_file()])
        if found:
            return found

    # No path found.
    raise MessageEventHistoryConfigError(
        "Message event store not configured or no store file found.",
        details={
            "env_var": _ENV_STORE_PATH,
            "state_dir": str(sd),
            "checked": [str(p) for p in candidates],
        },
    )


def _extract_first(d: Mapping[str, Any], keys: Iterable[str]) -> Any | None:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _extract_message_id(payload: Mapping[str, Any]) -> str | None:
    # Flattened keys first
    value = _extract_first(
        payload,
        [
            "message_id",
            "messageId",
            "messageID",
            "message_sid",
            "messageSid",
            "MessageSid",
            "sid",
            "Sid",
            "id",
            "Id",
        ],
    )
    if isinstance(value, str) and value.strip():
        return value.strip()

    # Nested common shapes: {"data": {...}}, {"payload": {...}}, {"message": {...}}
    for nest_key in ("data", "payload", "message"):
        nested = payload.get(nest_key)
        if isinstance(nested, Mapping):
            mid = _extract_message_id(nested)
            if mid:
                return mid

    return None


def _extract_event_type(payload: Mapping[str, Any]) -> str:
    value = _extract_first(
        payload,
        [
            "event_type",
            "eventType",
            "event",
            "type",
            "status",
            "message_status",
            "messageStatus",
            "MessageStatus",
            "action",
        ],
    )
    if isinstance(value, str) and value.strip():
        return value.strip()
    if value is None:
        return "unknown"
    return str(value)


def _extract_occurred_at(payload: Mapping[str, Any]) -> str | None:
    value = _extract_first(
        payload,
        [
            "occurred_at",
            "occurredAt",
            "timestamp",
            "time",
            "created_at",
            "createdAt",
            "date",
            "ts",
        ],
    )
    return _parse_timestamp(value)


def _validate_message_id(message_id: str) -> str:
    if not isinstance(message_id, str):
        raise MessageEventHistoryInvalidInputError("message_id must be a string.")
    message_id = message_id.strip()
    if not message_id:
        raise MessageEventHistoryInvalidInputError("message_id must be non-empty.")
    return message_id


def _validate_limit(limit: int) -> int:
    if not isinstance(limit, int):
        raise MessageEventHistoryInvalidInputError("limit must be an integer.")
    if limit < 1:
        raise MessageEventHistoryInvalidInputError("limit must be >= 1.")
    # Hard safety cap to keep output bounded for automation.
    return min(limit, 2000)


def _normalized_record(
    message_id: str, event_type: str, occurred_at: str, raw_event: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "schema": SCHEMA_ID,
        "message_id": message_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "raw": raw_event,
    }


# -----------------------------
# Public API
# -----------------------------


def append_message_event(
    raw_event: Mapping[str, Any],
    *,
    store_path: str | None = None,
    state_dir: str | None = None,
    clock: Callable[[], datetime] = _utc_now,
) -> MessageEvent:
    """Normalize and append a message event to the store.

    Intended for webhook handlers. Safe to call with provider-shaped payloads:
    we attempt to extract `message_id`, `event_type`, and timestamp.

    Raises:
        MessageEventHistoryInvalidInputError: if no message_id can be extracted.
        MessageEventHistoryExternalFailure: for IO failures.
    """
    if not isinstance(raw_event, Mapping):
        raise MessageEventHistoryInvalidInputError("raw_event must be a mapping/dict.")

    message_id = _extract_message_id(raw_event)
    if not message_id:
        raise MessageEventHistoryInvalidInputError("Could not extract message_id from event payload.")
    message_id = _validate_message_id(message_id)

    event_type = _extract_event_type(raw_event)

    occurred_at = _extract_occurred_at(raw_event) or _isoformat(clock())
    record = _normalized_record(message_id, event_type, occurred_at, raw_event)

    # Determine write target.
    try:
        if store_path:
            target = Path(store_path).expanduser()
        elif os.environ.get(_ENV_STORE_PATH):
            target = Path(os.environ[_ENV_STORE_PATH]).expanduser()
        else:
            sd = Path(state_dir).expanduser() if state_dir else _default_state_dir()
            target = sd / "messages" / "events.jsonl"

        target.parent.mkdir(parents=True, exist_ok=True)
        # Append-only JSONL. Sorting keys makes diffs stable in tests.
        with target.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            f.write("\n")
    except MessageEventHistoryError:
        raise
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        raise MessageEventHistoryExternalFailure(
            "Failed to persist message event.",
            details={"error": repr(e)},
        ) from e

    return MessageEvent(
        message_id=message_id, event_type=event_type, occurred_at=occurred_at, raw=raw_event, source_path=str(target)
    )


def get_message_event_history(request: MessageEventHistoryRequest) -> MessageEventHistoryResponse:
    """Read and return normalized events for a message_id."""
    message_id = _validate_message_id(request.message_id)
    limit = _validate_limit(request.limit)

    sources = _resolve_source_paths(store_path=request.store_path, state_dir=request.state_dir)

    # We only store events matching message_id, so we don't explode memory even with large stores.
    collected: list[tuple[int, str, datetime | None, MessageEvent]] = []
    global_line_idx = 0

    for path in sources:
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    global_line_idx += 1
                    s = line.strip()
                    if not s:
                        continue
                    try:
                        payload = json.loads(s)
                    except (json.JSONDecodeError, ValueError, KeyError):
                        # Skip unparsable lines (deterministic).
                        continue
                    if not isinstance(payload, Mapping):
                        continue

                    # Support both normalized records and raw provider payloads in logs.
                    raw_payload = payload.get("raw") if isinstance(payload.get("raw"), Mapping) else None
                    payload_mid = _extract_message_id(payload) or (
                        _extract_message_id(raw_payload) if raw_payload else None
                    )
                    if payload_mid != message_id:
                        continue

                    if payload.get("schema") == SCHEMA_ID or (
                        "message_id" in payload and "event_type" in payload and "raw" in payload
                    ):
                        ev_type = str(payload.get("event_type") or "unknown")
                        occurred_str = _parse_timestamp(payload.get("occurred_at")) or _extract_occurred_at(payload)
                        raw = raw_payload if raw_payload is not None else payload
                    else:
                        ev_type = _extract_event_type(payload)
                        occurred_str = _extract_occurred_at(payload)
                        raw = payload

                    occurred_dt = _coerce_dt(occurred_str) if occurred_str else None

                    ev = MessageEvent(
                        message_id=message_id,
                        event_type=ev_type,
                        occurred_at=occurred_str,
                        raw=raw,
                        source_path=str(path),
                    )
                    collected.append((global_line_idx, occurred_str or "", occurred_dt, ev))
        except FileNotFoundError:
            continue
        except MessageEventHistoryError:
            raise
        except (OSError, ConnectionError) as e:
            raise MessageEventHistoryExternalFailure(
                "Failed to read message events.",
                details={"path": str(path), "error": repr(e)},
            ) from e

    # Sort:
    # - Prefer parsed datetime when available
    # - Fall back to occurred_at string
    # - Tie-breaker: read order (global_line_idx)
    def _sort_key(item: tuple[int, str, datetime | None, MessageEvent]) -> tuple[int, float, str, int]:
        idx, occurred_str, occurred_dt, _ = item
        if occurred_dt is not None:
            return (0, occurred_dt.timestamp(), occurred_str, idx)
        # Unknown timestamps sort after known ones, but keep stable ordering.
        return (1, float("inf"), occurred_str, idx)

    collected_sorted = sorted(collected, key=_sort_key)
    limited = [ev for _, _, _, ev in collected_sorted][-limit:]

    return MessageEventHistoryResponse(
        message_id=message_id,
        events=limited,
        source_paths=[str(p) for p in sources],
    )


def response_to_json(response: MessageEventHistoryResponse) -> dict[str, Any]:
    return {
        "message_id": response.message_id,
        "events": [
            {
                "message_id": e.message_id,
                "event_type": e.event_type,
                "occurred_at": e.occurred_at,
                "raw": e.raw,
                "source_path": e.source_path,
            }
            for e in response.events
        ],
        "source_paths": list(response.source_paths),
        "schema": "thomas.messages.event_history.v1",
    }


# Convenience aliases (used by server routes / older call sites)
record_message_event = append_message_event
log_message_event = append_message_event
store_message_event = append_message_event
save_message_event = append_message_event
persist_message_event = append_message_event

fetch_message_event_history = get_message_event_history
read_message_event_history = get_message_event_history
list_message_event_history = get_message_event_history
list_message_events = get_message_event_history
