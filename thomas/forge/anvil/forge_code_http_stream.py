"""Byte-safe transcript decoding and HTTP stream frame translation."""

import codecs
import json
import typing

_PROGRESS_STATES = {"running", "completed", "failed", "cancelled", "interrupted"}
_AGENT_STATES = _PROGRESS_STATES | {"starting", "queued", "retrying", "quota_wait", "stopped"}
_PROGRESS_COUNTS = ("queued", "running", "integrated", "failed", "cancelled", "interrupted")
_PLAN_STATUSES = {"pending", "in_progress", "completed", "blocked"}
# Fields the Build screen reads off a frame: when it happened, the file a tool touched and the lines it changed,
# and the run-control events (plan, ask/answered, steering, paused/resumed; see thomas/forge/anvil/run_control.py).
_TEXT_KEYS = ("agent_id", "agent_title", "agent_mode", "model", "receipt", "team_id", "parent_agent_id")
_ID_KEYS = ("steer_id", "question_id", "path", "question")
_COUNT_KEYS = ("ts", "added", "removed", "paused_ms")
# What a Ran / Checked work row names: the command line and the check, cut to one row's worth.
_LABEL_KEYS = {"command": 300, "check": 300}


def _count(value: typing.Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _plan_items(value: typing.Any) -> list[dict[str, typing.Any]] | None:
    if not isinstance(value, list):
        return None
    items = []
    for item in value[:30]:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"].strip():
            continue
        status = item.get("status")
        items.append(
            {
                "id": str(item.get("id") or ""),
                "text": item["text"][:300],
                "status": status if status in _PLAN_STATUSES else "pending",
                "owner": str(item.get("owner") or "")[:80],
                "started_at": _count(item.get("started_at")),
                "done_at": _count(item.get("done_at")),
            }
        )
    return items


def _ask_options(value: typing.Any) -> list[dict[str, typing.Any]] | None:
    if not isinstance(value, list):
        return None
    options = []
    for option in value[:6]:
        if not isinstance(option, dict) or not isinstance(option.get("label"), str) or not option["label"].strip():
            continue
        options.append(
            {
                "label": option["label"][:120],
                "description": str(option.get("description") or "")[:400],
                "recommended": option.get("recommended") is True,
            }
        )
    return options


def _team_progress(value: typing.Any) -> dict[str, typing.Any] | None:
    if not isinstance(value, dict):
        return None
    state = value.get("state")
    total = value.get("total")
    if not isinstance(state, str) or state not in _PROGRESS_STATES:
        return None
    if isinstance(total, bool) or not isinstance(total, int) or total < 1:
        return None
    if any(
        isinstance(value.get(key), bool) or not isinstance(value.get(key), int) or value[key] < 0
        for key in _PROGRESS_COUNTS
    ):
        return None
    if sum(value[key] for key in _PROGRESS_COUNTS) != total:
        return None
    return {"state": state, "total": total, **{key: value[key] for key in _PROGRESS_COUNTS}}


def line_to_sse_payload(line: str) -> dict[str, typing.Any]:
    """Map one transcript line to a typed SSE payload when possible."""

    stripped = line.strip()
    if not stripped:
        return {}
    if stripped[0] == "{":
        try:
            obj = json.loads(stripped)
        except (json.JSONDecodeError, TypeError):
            obj = None
        if isinstance(obj, dict) and obj.get("fc"):
            payload: dict[str, typing.Any] = {
                "type": "output",
                "kind": str(obj.get("fc")),
                "text": str(obj.get("text") or ""),
            }
            if obj.get("name"):
                payload["name"] = str(obj.get("name"))
            if obj.get("is_error"):
                payload["is_error"] = True
            if obj.get("delta"):
                payload["delta"] = True
            # `receipt` marks a model report among the meta lines (build_model_receipt.py).
            for key in _TEXT_KEYS + _ID_KEYS:
                value = obj.get(key)
                if isinstance(value, str) and value.strip():
                    payload[key] = value[:1000] if key in _ID_KEYS else value
            for key, limit in _LABEL_KEYS.items():
                value = obj.get(key)
                if isinstance(value, str) and value.strip():
                    payload[key] = value[:limit]
            for key in _COUNT_KEYS:
                if (count := _count(obj.get(key))) is not None:
                    payload[key] = count
            if isinstance(obj.get("answer"), str):
                payload["answer"] = obj["answer"][:8000]
            if isinstance(obj.get("allow_free_text"), bool):
                payload["allow_free_text"] = obj["allow_free_text"]
            if (items := _plan_items(obj.get("items"))) is not None and obj.get("fc") == "plan":
                payload["items"] = items
            if (options := _ask_options(obj.get("options"))) is not None:
                payload["options"] = options
            state = obj.get("agent_state")
            if isinstance(state, str) and state in _AGENT_STATES:
                payload["agent_state"] = state
            if "team_progress" in obj:
                progress = _team_progress(obj["team_progress"])
                if progress is not None:
                    payload["team_progress"] = progress
            return payload
    return {"type": "output", "text": line}


class IncrementalLineDecoder:
    """Decode arbitrary UTF-8 chunks while retaining split chars and lines."""

    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._buffer = ""

    def feed(self, chunk: bytes) -> list[str]:
        if chunk:
            self._buffer += self._decoder.decode(chunk)
        *lines, self._buffer = self._buffer.split("\n")
        return lines

    def flush(self) -> list[str]:
        self._buffer += self._decoder.decode(b"", final=True)
        parts = self._buffer.split("\n")
        self._buffer = ""
        remainder = parts.pop() if parts else ""
        if remainder.strip():
            parts.append(remainder)
        return parts
