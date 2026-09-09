from __future__ import annotations

import json
import time
import uuid
from typing import Any

# -----------------------
# Wire protocol
# -----------------------
# All JSON messages have:
# - t: message type (string)
# - id: message id (client-generated ok)
# - ts: client/server unix ms
#
# Binary messages are audio chunks (see ws_handler.py).


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id(prefix: str = "m") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class ProtocolError(ValueError):
    pass


def _require(obj: dict, k: str, typ):
    if k not in obj:
        raise ProtocolError(f"missing field: {k}")
    v = obj[k]
    if not isinstance(v, typ):
        raise ProtocolError(f"field {k} must be {typ.__name__}")
    return v


def parse_json_message(raw: str) -> dict[str, Any]:
    try:
        obj = json.loads(raw)
    except Exception as e:
        raise ProtocolError(f"invalid json: {e}") from e
    if not isinstance(obj, dict):
        raise ProtocolError("message must be a JSON object")
    _require(obj, "t", str)
    obj.setdefault("id", new_id("m"))
    obj.setdefault("ts", now_ms())
    return obj


def make(t: str, **kwargs) -> dict[str, Any]:
    base = {"t": t, "id": new_id("s"), "ts": now_ms()}
    base.update(kwargs)
    return base


# Common message types (client -> server):
# - hello: {t:"hello", client:{ua, tz}, session:{id?}, mode}
# - text: {t:"text", text, attachments?, mode?}
# - stt: {t:"stt", text, is_final, confidence, seq, src}
# - interrupt: {t:"interrupt", reason}
# - ping: {t:"ping", n}
# - telemetry: {t:"telemetry", kind, value, meta?}
# - pin_goal: {t:"pin_goal", goal:{title, details?}}
# - unpin_goal: {t:"unpin_goal", goal_id}
#
# server -> client:
# - ready: {t:"ready", session:{id}, server:{version}, cfg:{...}}
# - assistant_delta: {t:"assistant_delta", text}
# - assistant_done: {t:"assistant_done", usage?, quality?}
# - intent: {t:"intent", intent:{name, confidence, slots?}, suggestions:[...]}
# - nudge: {t:"nudge", nudge:{title, text, kind, confidence}}
# - error: {t:"error", code, message, retryable}
# - pong: {t:"pong", n}
# - metrics: {t:"metrics", telemetry:{...}, quality:{...}}

# - audio_begin: {t:"audio_begin", mime}
