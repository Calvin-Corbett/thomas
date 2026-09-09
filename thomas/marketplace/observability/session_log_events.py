"""Session-log event vocabulary for the run_store spine.

Model-visible means logged: every message list that reaches an LLM client,
and every mutation of the history that produced it, is an event on the
pre-existing run_store spine (run_id + monotonic seq). This module adds no
new ledger -- it defines the event type constants and the payload builders
that later tasks (the capture hook, the history-mutation call sites, and the
derivation/shadow-diff pass) write through.

Public API:
- Event type constants: MODEL_REQUEST, MODEL_RESPONSE, CONTEXT_INJECT,
  HISTORY_COMPACTION, HISTORY_TRUNCATE, HISTORY_FORK, HISTORY_IMPORTED
- Payload builders: model_request_payload, model_response_payload,
  compaction_payload, truncate_payload, fork_payload, imported_payload

Every builder validates its inputs and raises ValueError naming the missing
or malformed field -- loud, never lenient; a payload garbage enough to be
misread as something else must never reach the spine silently. Builders
return plain dicts ready to pass as run_store.append_event()'s `payload`
argument; each includes its own "type" key so it round-trips unchanged
through run_store.stream_replay() (which only fills in "type" from the
stored event_type when the payload lacks one).
"""

from __future__ import annotations

from typing import Any

MODEL_REQUEST = "model/request"
MODEL_RESPONSE = "model/response"
CONTEXT_INJECT = "context/inject"
HISTORY_COMPACTION = "history/compaction"
HISTORY_TRUNCATE = "history/truncate"
HISTORY_FORK = "history/fork"
HISTORY_IMPORTED = "history/imported"

# compaction_payload's `reconstruction` field: "exact" means the recorded
# spliced_role/spliced_content faithfully represent a single-message splice
# over [replaced_from, replaced_to) -- safe to replay verbatim. "lossy-
# fallback" means the compactor's progressive heuristic-trim fallback did
# more than that one clean splice (dropped some messages within the range
# without replacing them 1:1), so replaying spliced_role/spliced_content as
# if it were a clean splice would delete real, still-present content. A
# reader MUST decline to reconstruct when it sees "lossy-fallback" rather
# than guess.
RECONSTRUCTION_EXACT = "exact"
RECONSTRUCTION_LOSSY_FALLBACK = "lossy-fallback"
_RECONSTRUCTION_VALUES = {RECONSTRUCTION_EXACT, RECONSTRUCTION_LOSSY_FALLBACK}


def _require_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing or invalid required field: {name!r}")
    return value


def _require_optional_str(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"missing or invalid required field: {name!r}")
    return value


def _require_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"missing or invalid required field: {name!r}")
    return value


def _require_non_negative_int(value: Any, name: str) -> int:
    value = _require_int(value, name)
    if value < 0:
        raise ValueError(f"missing or invalid required field: {name!r}")
    return value


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"missing or invalid required field: {name!r}")
    return value


def _require_list(value: Any, name: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"missing or invalid required field: {name!r}")
    return value


def _require_dict(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"missing or invalid required field: {name!r}")
    return value


def model_request_payload(
    messages: list[dict],
    model: str,
    provider: str,
    tools_digest: str | None,
    correlation: str,
) -> dict[str, Any]:
    """The exact message list handed to the LLM client for one request."""
    return {
        "type": MODEL_REQUEST,
        "messages": _require_list(messages, "messages"),
        "model": _require_str(model, "model"),
        "provider": _require_str(provider, "provider"),
        "tools_digest": _require_optional_str(tools_digest, "tools_digest"),
        "correlation": _require_str(correlation, "correlation"),
    }


def model_response_payload(
    text: str,
    tool_calls: list,
    usage: dict,
    interrupted: bool,
    request_seq: int,
    *,
    served_by_model: str,
    served_by_provider: str,
    provider_attempts: int,
    merged_partial_output: bool,
) -> dict[str, Any]:
    """What the model returned for the request at `request_seq`.

    `served_by_model`/`served_by_provider` are read at completion time --
    whichever attempt was actually active when the stream ended -- and are
    NOT assumed to match the model/request event's `model`/`provider`:
    failover can switch providers mid-call, so the request records what was
    asked and the response records what actually served. `provider_attempts`
    counts every attempt this call made (always >= 1). `merged_partial_output`
    is true when tokens actually arrived from more than one attempt (e.g. a
    primary that streamed partial text before dying, then a fallback that
    completed) -- the honesty spine never lets that read as one clean
    single-provider response.
    """
    if not isinstance(text, str):
        raise ValueError("missing or invalid required field: 'text'")
    provider_attempts = _require_int(provider_attempts, "provider_attempts")
    if provider_attempts < 1:
        raise ValueError("missing or invalid required field: 'provider_attempts' (must be >= 1)")
    return {
        "type": MODEL_RESPONSE,
        "text": text,
        "tool_calls": _require_list(tool_calls, "tool_calls"),
        "usage": _require_dict(usage, "usage"),
        "interrupted": _require_bool(interrupted, "interrupted"),
        "request_seq": _require_int(request_seq, "request_seq"),
        "served_by_model": _require_str(served_by_model, "served_by_model"),
        "served_by_provider": _require_str(served_by_provider, "served_by_provider"),
        "provider_attempts": provider_attempts,
        "merged_partial_output": _require_bool(merged_partial_output, "merged_partial_output"),
    }


def compaction_payload(
    summary_text: str,
    replaced_from: int,
    replaced_to: int,
    by: str,
    spliced_role: str,
    spliced_content: str,
    reconstruction: str = RECONSTRUCTION_EXACT,
) -> dict[str, Any]:
    """One history/compaction event: the replaced range and the message that actually replaced it.

    `spliced_role`/`spliced_content` are the ROLE and CONTENT of the message
    the compactor actually spliced into the conversation -- not
    `summary_text` (the raw summarization output) re-wrapped by a reader's
    guess. A deriver that reconstructs the splice from `summary_text` alone
    would have to re-implement the compactor's own marker/wrapper format and
    would drift the moment that format changes; recording the verbatim
    spliced message here means a deriver only ever replays what actually
    happened, never re-imagines it.
    """
    replaced_from = _require_non_negative_int(replaced_from, "replaced_from")
    replaced_to = _require_non_negative_int(replaced_to, "replaced_to")
    if replaced_to < replaced_from:
        raise ValueError("missing or invalid required field: 'replaced_to' (precedes replaced_from)")
    if reconstruction not in _RECONSTRUCTION_VALUES:
        raise ValueError(
            f"missing or invalid required field: 'reconstruction' (must be one of {sorted(_RECONSTRUCTION_VALUES)})"
        )
    return {
        "type": HISTORY_COMPACTION,
        "summary_text": _require_str(summary_text, "summary_text"),
        "replaced_from": replaced_from,
        "replaced_to": replaced_to,
        "by": _require_str(by, "by"),
        "spliced_role": _require_str(spliced_role, "spliced_role"),
        "spliced_content": _require_str(spliced_content, "spliced_content"),
        "reconstruction": reconstruction,
    }


def truncate_payload(kept: int, dropped: int) -> dict[str, Any]:
    """One history/truncate event: how many messages were kept vs dropped."""
    return {
        "type": HISTORY_TRUNCATE,
        "kept": _require_non_negative_int(kept, "kept"),
        "dropped": _require_non_negative_int(dropped, "dropped"),
    }


def fork_payload(parent_session: str, boundary_len: int) -> dict[str, Any]:
    """One history/fork event: the parent session and the fork boundary."""
    return {
        "type": HISTORY_FORK,
        "parent_session": _require_str(parent_session, "parent_session"),
        "boundary_len": _require_non_negative_int(boundary_len, "boundary_len"),
    }


def imported_payload(message_count: int, source: str) -> dict[str, Any]:
    """One history/imported event: a pre-existing session's legacy message count."""
    return {
        "type": HISTORY_IMPORTED,
        "message_count": _require_non_negative_int(message_count, "message_count"),
        "source": _require_str(source, "source"),
    }
