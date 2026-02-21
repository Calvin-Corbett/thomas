"""P064 - Message poll vote and close (Thomas-native).

This prompt implements a single operation that:
  1) casts a vote in a message poll, then
  2) closes that poll.

Design goals:
- Backend-agnostic: works with any messages backend that exposes poll vote/close APIs.
- Deterministic errors: stable error codes and structured details for automation.
- Friendly to CLI + automation: a small wrapper can emit stable JSON.

The code intentionally avoids OpenClaw naming reuse. The only "P064" reference is
for internal prompt-pack tracking.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, Optional, Protocol, Union


PROMPT_ID = "P064"
DOMAIN = "messages"


class MessagePollVoteAndCloseError(RuntimeError):
    """Deterministic error for vote+close poll."""

    def __init__(self, code: str, message: str, *, details: Optional[Mapping[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": str(self),
                "details": self.details,
            },
        }


@dataclass(frozen=True, slots=True)
class PollVoteAndCloseRequest:
    """Input contract."""

    poll_id: str
    option: str
    voter_id: Optional[str] = None
    reason: Optional[str] = None


@dataclass(frozen=True, slots=True)
class PollVoteAndCloseResult:
    """Output contract."""

    poll_id: str
    option: str
    voted: bool
    closed: bool
    vote_receipt: Optional[Mapping[str, Any]] = None
    close_receipt: Optional[Mapping[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "poll_id": self.poll_id,
            "option": self.option,
            "voted": self.voted,
            "closed": self.closed,
            "vote_receipt": dict(self.vote_receipt or {}),
            "close_receipt": dict(self.close_receipt or {}),
        }


class MessagesPollBackend(Protocol):
    """Minimal capability protocol expected from a messages backend."""

    # Keyword-friendly signatures are preferred, but we also support positional fallbacks.
    def poll_vote(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Any: ...

    def poll_close(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Any: ...


def _validate_request(req: PollVoteAndCloseRequest) -> None:
    if not isinstance(req.poll_id, str) or not req.poll_id.strip():
        raise MessagePollVoteAndCloseError(
            "invalid_input",
            "poll_id must be a non-empty string",
            details={"field": "poll_id"},
        )
    if not isinstance(req.option, str) or not req.option.strip():
        raise MessagePollVoteAndCloseError(
            "invalid_input",
            "option must be a non-empty string",
            details={"field": "option"},
        )


def _coerce_mapping(value: Any) -> Optional[Mapping[str, Any]]:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "__dict__"):
        try:
            return dict(value.__dict__)
        except Exception:
            return {"value": repr(value)}
    return {"value": value}


def _get_messages_client(config: Optional[Mapping[str, Any]] = None) -> Any:
    """Resolve a messages client/backend from the surrounding runtime.

    This function is intentionally defensive: Thomas deployments may wire their
    runtime differently (DI container, module-level resolver, config mapping, etc.).
    """

    # 1) Common resolver entrypoints (best-effort; safe if absent).
    for mod_name, fn_name in [
        ("thomas.messages.clients", "get_client"),
        ("thomas.messages.client", "get_client"),
        ("thomas.messages", "get_client"),
    ]:
        try:
            mod = __import__(mod_name, fromlist=[fn_name])
            fn = getattr(mod, fn_name)
        except Exception:
            continue
        try:
            return fn(config=config)  # type: ignore[misc]
        except TypeError:
            # Resolver may not accept keyword args.
            try:
                return fn(config)  # type: ignore[misc]
            except Exception:
                continue
        except Exception:
            continue

    # 2) Config can directly provide a backend client (tests/embedded runtimes).
    if isinstance(config, Mapping):
        client = config.get("messages_client") or config.get("messages") or config.get("client")
        if client is not None:
            return client

    raise MessagePollVoteAndCloseError(
        "missing_config",
        "No messages backend configured (unable to resolve a messages client)",
    )


def _resolve_backend_methods(backend: Any) -> tuple[Any, Any]:
    vote_fn = None
    close_fn = None

    for name in (
        "poll_vote",
        "vote_poll",
        "message_poll_vote",
        "vote_in_poll",
        "vote",
    ):
        if hasattr(backend, name):
            vote_fn = getattr(backend, name)
            break

    for name in (
        "poll_close",
        "close_poll",
        "message_poll_close",
        "stop_poll",
        "close",
    ):
        if hasattr(backend, name):
            close_fn = getattr(backend, name)
            break

    if vote_fn is None:
        raise MessagePollVoteAndCloseError(
            "missing_backend_capability",
            "Messages backend does not support poll voting",
            details={"required": "poll_vote"},
        )
    if close_fn is None:
        raise MessagePollVoteAndCloseError(
            "missing_backend_capability",
            "Messages backend does not support poll closing",
            details={"required": "poll_close"},
        )

    return vote_fn, close_fn


def _call_vote(vote_fn: Any, req: PollVoteAndCloseRequest) -> Any:
    """Call backend vote function with graceful fallbacks."""
    # Preferred: keyword call with full info.
    try:
        return vote_fn(
            poll_id=req.poll_id,
            option=req.option,
            voter_id=req.voter_id,
            reason=req.reason,
        )
    except TypeError:
        # Try dropping optional params progressively (signatures vary).
        try:
            return vote_fn(poll_id=req.poll_id, option=req.option, voter_id=req.voter_id)
        except TypeError:
            try:
                return vote_fn(poll_id=req.poll_id, option=req.option)
            except TypeError:
                return vote_fn(req.poll_id, req.option, req.voter_id)


def _call_close(close_fn: Any, req: PollVoteAndCloseRequest) -> Any:
    """Call backend close function with graceful fallbacks."""
    # Preferred: keyword call.
    try:
        return close_fn(poll_id=req.poll_id, reason=req.reason)
    except TypeError:
        try:
            return close_fn(poll_id=req.poll_id)
        except TypeError:
            return close_fn(req.poll_id)


def vote_and_close_poll(
    req: PollVoteAndCloseRequest,
    *,
    config: Optional[Mapping[str, Any]] = None,
    client: Any = None,
) -> PollVoteAndCloseResult:
    """Cast a poll vote then close the poll.

    Raises:
        MessagePollVoteAndCloseError with codes:
          - invalid_input
          - missing_config
          - missing_backend_capability
          - external_failure
    """

    _validate_request(req)
    backend = client if client is not None else _get_messages_client(config)
    vote_fn, close_fn = _resolve_backend_methods(backend)

    # Vote.
    try:
        vote_receipt = _call_vote(vote_fn, req)
    except MessagePollVoteAndCloseError:
        raise
    except Exception as e:
        raise MessagePollVoteAndCloseError(
            "external_failure",
            "Poll vote failed",
            details={"stage": "vote", "error": repr(e)},
        ) from e

    # Close.
    try:
        close_receipt = _call_close(close_fn, req)
    except MessagePollVoteAndCloseError:
        raise
    except Exception as e:
        raise MessagePollVoteAndCloseError(
            "external_failure",
            "Poll close failed",
            details={"stage": "close", "error": repr(e), "vote_receipt": _coerce_mapping(vote_receipt) or {}},
        ) from e

    return PollVoteAndCloseResult(
        poll_id=req.poll_id,
        option=req.option,
        voted=True,
        closed=True,
        vote_receipt=_coerce_mapping(vote_receipt),
        close_receipt=_coerce_mapping(close_receipt),
    )


def run(
    payload: Union[Mapping[str, Any], PollVoteAndCloseRequest],
    *,
    config: Optional[Mapping[str, Any]] = None,
    client: Any = None,
) -> Mapping[str, Any]:
    """Compatibility entrypoint returning a plain mapping."""

    if isinstance(payload, PollVoteAndCloseRequest):
        req = payload
    else:
        req = PollVoteAndCloseRequest(
            poll_id=str(payload.get("poll_id", "")),
            option=str(payload.get("option", "")),
            voter_id=payload.get("voter_id"),
            reason=payload.get("reason"),
        )

    result = vote_and_close_poll(req, config=config, client=client)
    return result.to_dict()


def safe_run(
    payload: Union[Mapping[str, Any], PollVoteAndCloseRequest],
    *,
    config: Optional[Mapping[str, Any]] = None,
    client: Any = None,
) -> Mapping[str, Any]:
    """Run but return a deterministic error payload instead of raising."""

    try:
        return run(payload, config=config, client=client)
    except MessagePollVoteAndCloseError as e:
        return e.to_dict()


def to_json(data: Mapping[str, Any]) -> str:
    """Stable JSON serializer used by CLI wrappers."""

    return json.dumps(data, sort_keys=True, separators=(",", ":"))
