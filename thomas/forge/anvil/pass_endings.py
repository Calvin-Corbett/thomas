"""What the engine does when a Build pass ends early.

A pass that ended for any reason other than its wall clock -- an unmet contract
the completion gate refused, the 400-iteration cap, a full context window, three
identical tool failures, a provider error -- used to end the whole Build: the
translator set rc 1, the engine verified only rc 0, and the files left behind
were never checked (thomas-harness.md K1). A run that built most of a game and
missed one checked item read "agent loop exited 1".

Here each ending becomes a decision:

- ``continue``: another pass with the original brief and a short note of what
  happened and what is left. The engine verifies whatever changed first, so this
  is also "verify, then decide" -- the checks run, and the synthetic contract
  item below keeps the Build from being filed as done on a pass that did not end
  on its own.
- ``ask``: the next move is genuinely the person's (sign-in, quota, a spending
  ceiling). The Build stops and says so in the hand-in, naming what it needs.
- ``stop``: nothing more a pass can do; the honest outcome is reported.

Bounded by progress, not time: two passes in a row that end the same way and
change nothing stop the retries, inside the run's existing pass budget.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONTINUE = "continue"
ASK = "ask"
STOP = "stop"

# The kinds of early ending, from the loop's own AGENT_ERROR payloads.
CONTRACT_UNMET = "contract_unmet"
ITERATION_CAP = "iteration_cap"
CONTEXT_FULL = "context_full"
REPEATED_TOOL_FAILURE = "repeated_tool_failure"
PROVIDER_TRANSIENT = "provider_transient"
PROVIDER_PERMANENT = "provider_permanent"
TOKEN_CEILING = "token_ceiling"
UNKNOWN = "unknown"

_LABELS = {
    CONTRACT_UNMET: "the completion gate refused to finish it: the acceptance contract was not met",
    ITERATION_CAP: "it used its whole step allowance while work was still active",
    CONTEXT_FULL: "its context window filled up",
    REPEATED_TOOL_FAILURE: "the same tool call failed three times in a row",
    PROVIDER_TRANSIENT: "the model provider returned a temporary error",
    PROVIDER_PERMANENT: "the model provider refused the request",
    TOKEN_CEILING: "it reached the run's token ceiling",
    UNKNOWN: "the agent loop reported an error",
}

_DECISIONS = {
    CONTRACT_UNMET: CONTINUE,
    ITERATION_CAP: CONTINUE,
    CONTEXT_FULL: CONTINUE,  # a new pass starts with an empty conversation
    REPEATED_TOOL_FAILURE: CONTINUE,
    PROVIDER_TRANSIENT: CONTINUE,
    PROVIDER_PERMANENT: ASK,
    TOKEN_CEILING: ASK,  # a spending limit is the person's to raise
    UNKNOWN: STOP,
}

_TRANSIENT_STATUSES = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524, 529})
_PERMANENT_STATUSES = frozenset({400, 401, 402, 403, 404, 413, 422})
_TRANSIENT_WORDS = (
    "lost the connection",
    "connection",
    "timed out",
    "timeout",
    "temporarily",
    "overloaded",
    "incomplete",
    "server error",
    "try again",
    "disconnect",
)


@dataclass(frozen=True)
class PassEnding:
    """How one pass ended early, classified from the loop's error payload."""

    kind: str
    text: str

    @property
    def decision(self) -> str:
        return _DECISIONS.get(self.kind, STOP)

    @property
    def label(self) -> str:
        return _LABELS.get(self.kind, _LABELS[UNKNOWN])


def classify_agent_error(data: dict[str, Any] | None) -> PassEnding:
    """Classify an ``AGENT_ERROR`` payload. Structural fields first, the loop's fixed messages second."""
    from thomas.agent.completion_gate import GATE_BLOCKED_ERROR

    data = data if isinstance(data, dict) else {}
    text = str(data.get("error") or "").strip()
    low = text.lower()
    if str(data.get("stop_reason") or "") == "token_ceiling_reached":
        return PassEnding(TOKEN_CEILING, text)
    status = int(data.get("status") or 0) if str(data.get("status") or "0").isdigit() else 0
    if status or "retryable" in data or "error_code" in data:
        quota = "quota" in low or "insufficient" in low or "billing" in low or "usage limit" in low
        if not quota and (bool(data.get("retryable")) or status in _TRANSIENT_STATUSES or status >= 500):
            return PassEnding(PROVIDER_TRANSIENT, text)
        if quota or status in _PERMANENT_STATUSES:
            return PassEnding(PROVIDER_PERMANENT, text)
        if any(word in low for word in _TRANSIENT_WORDS):
            return PassEnding(PROVIDER_TRANSIENT, text)
        return PassEnding(PROVIDER_PERMANENT, text)
    if text.startswith(GATE_BLOCKED_ERROR):
        return PassEnding(CONTRACT_UNMET, text)
    if low.startswith("pass budget exhausted"):
        return PassEnding(ITERATION_CAP, text)
    if low.startswith("tool loop stability issue"):
        return PassEnding(REPEATED_TOOL_FAILURE, text)
    if (
        low.startswith("the request cannot hold")
        or ("context window" in low and "cannot fit" in low)
        or "token message budget" in low
        or low.startswith("required system/developer instructions")
    ):
        return PassEnding(CONTEXT_FULL, text)
    if low.startswith("lost the connection") or "could not connect" in low:
        return PassEnding(PROVIDER_TRANSIENT, text)
    return PassEnding(UNKNOWN, text)


def ending_contract(ending: PassEnding) -> dict[str, Any]:
    """An unmet settlement standing in for a pass that did not end on its own.

    Like the wall-clock contract, it keeps ``completed`` out of reach until a
    later pass ends by itself and settles the real contract."""
    item_id = f"pass:{ending.kind.replace('_', '-')}"
    detail = (ending.text[:600] or ending.label) + "; continue exactly where it left off; do not start over"
    return {
        "active": True,
        "verdict": {"met": False, "unmet": [item_id], "unchecked": []},
        "items": [
            {
                "item_id": item_id,
                "kind": "requirement",
                "description": f"The previous pass ended early because {ending.label}.",
                "checked": True,
                "satisfied": False,
                "detail": detail,
            }
        ],
    }


def workspace_fingerprint(cwd: str | Path, changed: list[str]) -> str:
    """A hash of the changed files' names and bytes: equal before and after a pass that changed nothing."""
    digest = hashlib.sha256()
    for name in sorted(str(c) for c in changed or []):
        digest.update(name.encode("utf-8", "replace") + b"\0")
        try:
            digest.update((Path(cwd) / name).read_bytes())
        except OSError:
            digest.update(b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()


class ProgressWatch:
    """Stops retries when two consecutive early-ending passes change nothing and end the same way."""

    def __init__(self) -> None:
        self._last: tuple[str, str] | None = None

    def stalled(self, ending: PassEnding, fingerprint_before: str, fingerprint_after: str) -> bool:
        if fingerprint_before != fingerprint_after:
            self._last = None
            return False
        key = (ending.kind, "")
        repeated = self._last == key
        self._last = key
        return repeated

    def reset(self) -> None:
        self._last = None


__all__ = [
    "ASK",
    "CONTINUE",
    "STOP",
    "PassEnding",
    "ProgressWatch",
    "classify_agent_error",
    "ending_contract",
    "workspace_fingerprint",
]
