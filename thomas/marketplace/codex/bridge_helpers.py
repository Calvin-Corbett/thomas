"""Pure helpers extracted from bridge.py to keep that file under monolith cap.

These are re-imported by ``bridge`` with underscore-prefixed aliases that
``tests/test_codex_bridge_usage.py`` and the bridge's internal call sites use.
"""

from __future__ import annotations

from typing import Any


def extract_usage_payload(payload: Any) -> dict[str, int] | None:
    """Normalize token usage from app-server payloads when available."""

    def _coerce_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return max(0, int(value))
        except (TypeError, ValueError, OverflowError):
            return None

    candidates: list[Any] = []
    if isinstance(payload, dict):
        token_usage = payload.get("tokenUsage")
        candidates.extend(
            [
                payload.get("usage"),
                payload.get("usageMetadata"),
                token_usage.get("last") if isinstance(token_usage, dict) else None,
                token_usage.get("total") if isinstance(token_usage, dict) else None,
                token_usage,
                payload,
            ]
        )

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue

        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        total_tokens: int | None = None

        for key in ("prompt_tokens", "input_tokens", "inputTokens", "prompt_token_count", "prompt", "input"):
            prompt_tokens = _coerce_int(candidate.get(key))
            if prompt_tokens is not None:
                break
        for key in (
            "completion_tokens",
            "output_tokens",
            "outputTokens",
            "candidates_token_count",
            "completion",
            "output",
        ):
            completion_tokens = _coerce_int(candidate.get(key))
            if completion_tokens is not None:
                break
        for key in ("total_tokens", "total_token_count", "totalTokens"):
            total_tokens = _coerce_int(candidate.get(key))
            if total_tokens is not None:
                break

        if prompt_tokens is None and completion_tokens is None and total_tokens is None:
            continue

        prompt = int(prompt_tokens or 0)
        completion = int(completion_tokens or 0)
        total = int(total_tokens if total_tokens is not None else (prompt + completion))
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
        }

    return None


def event_matches_turn(params: dict[str, Any], *, thread_id: str | None, turn_id: str | None) -> bool:
    """Return False for app-server events from another thread or turn."""

    def _pick(container: Any, *keys: str) -> str:
        if not isinstance(container, dict):
            return ""
        for key in keys:
            value = container.get(key)
            if value:
                return str(value)
        return ""

    item = params.get("item") if isinstance(params, dict) else None
    turn = params.get("turn") if isinstance(params, dict) else None
    event_thread_id = _pick(params, "threadId", "thread_id") or _pick(item, "threadId", "thread_id")
    event_thread_id = event_thread_id or _pick(turn, "threadId", "thread_id")
    event_turn_id = _pick(params, "turnId", "turn_id") or _pick(item, "turnId", "turn_id")
    event_turn_id = event_turn_id or _pick(turn, "id", "turnId", "turn_id")
    if thread_id and event_thread_id and event_thread_id != str(thread_id):
        return False
    return not (turn_id and event_turn_id and event_turn_id != str(turn_id))
