"""Derive what the model saw, and shadow-diff it against what the loop built.

Task 4 of the honesty-spine plan closes the loop opened by Tasks 1-3: the
spine now RECORDS every message list handed to an LLM client (model/request,
model/response) and every history mutation that changes what the next
request will contain (history/compaction, history/truncate). This module
proves the log is enough to RECONSTRUCT that next request -- before any
builder in loop_execution.py is ever replaced by the derivation.

``derive_messages(events)`` is a pure function: given one run's replayed
events (as returned by ``run_store.stream_replay``), it reconstructs the
message list the run's NEXT model/request should contain. No I/O, no
run_store import, no side effects -- it is a fold over the events it is
handed and nothing else. That purity is per-function, not per-module: this
file also houses the (deliberately impure) shadow-soak wiring below --
``shadow_diff_if_enabled`` reads run_store and writes a divergence event --
kept alongside ``derive_messages`` per the plan's line-budget guidance
rather than split into a separate module.

Input scope (read this before trusting a "0 divergences" report):
- Only the events already on the CORRELATED run's own spine are read --
  the run ``set_capture_run`` tagged this turn's model calls with. That
  covers model/request, model/response, history/compaction and
  history/truncate, since Task 3 wired all four (compaction and truncate)
  to correlate the same way the model calls do.
- history/fork and history/imported are NOT applied by this fold. A fork
  starts an entirely new run (its own child run_id) rather than continuing
  this one, so its event is a marker on the CHILD run's spine, not something
  this run's derivation splices in. history/imported carries only a legacy
  message COUNT, not the imported content, so there is nothing to replay
  from it. Route-side truncate/imported events that land in the shared
  AMBIENT run rather than a turn-correlated run (Task 3's documented
  weaker-correlation case) are visible in that run's replay but are not
  stitched across runs by session identity here -- that cross-run
  correlation is bigger than this phase needs and is left as a named
  follow-up, not silently pretended to be covered.
- Tool-result messages that loop_execution.py appends directly to
  ``self._conversation`` are NOT captured as spine events by any task through
  Task 4 -- only the model-call boundary and the four history mutations are.
  A turn that used tools will therefore predictably diverge from the
  derivation once a tool result lands in the built list. That is not a bug
  in this module: it is the honest, visible edge of what phase 1 captures,
  and exactly the kind of gap the shadow soak exists to surface.

Comparison scope (also stated in the report tool's header and on every
shadow/divergence event): the shadow diff compares ROLE + CONTENT of
NON-SYSTEM messages only. System messages are excluded because
_build_messages assembles them from memory retrieval, skills context, the
autonomy profile and project instructions -- live sources the log does not
yet capture as context/inject events. Comparing them would show noise about
sources this phase never claimed to capture, not a fact about whether the
model-visible history is honestly logged. A comparison that quietly covered
less than "the built message list" while being reported as full-scope would
be exactly the kind of half-truth this whole plan exists to end -- so the
scope is named everywhere a result is shown, not just here.

Divergence noise classification: every ``shadow/divergence`` event carries a
cheap, heuristic ``reason`` tag (see ``classify_divergence``) --
``"contains-tool-role"`` when either side has a tool-role message or
tool_calls (the known, expected noise source named above), else
``"unclassified"``. This is a presence check, not proof of cause: it lets
the report tool separate expected-class noise from everything else without
claiming to have diagnosed any individual divergence.

The shadow flag (``THOMAS_HONESTY_SHADOW``) is read ONCE at import time into
``SHADOW_ENABLED`` -- changing the environment variable takes effect only on
the next process restart, never mid-process. Its OFF position (the default)
means ``shadow_diff_if_enabled`` returns before touching run_store, before
calling ``derive_messages``, before any I/O at all: zero behavior change.
"""

from __future__ import annotations

import copy
import logging
import os
import sqlite3
from collections.abc import Iterable
from typing import Any

from thomas.core import capture_context
from thomas.marketplace.observability import run_store
from thomas.marketplace.observability import session_log_events as sle

log = logging.getLogger(__name__)

SHADOW_DIVERGENCE = "shadow/divergence"
SHADOW_SKIP = "shadow/skip"

# The reason strings this module emits for a skip -- named as constants so
# the report tool and tests never hand-type them separately.
SKIP_REASON_LOSSY_COMPACTION_FALLBACK = "lossy-compaction-fallback"
# The compactor records replaced_from/replaced_to relative to the
# CONVERSATION it mutated (self._conversation, no leading system message).
# A derive_messages fold works in REQUEST space, seeded verbatim from a
# model/request event's `messages` -- which DOES carry the system message
# AgentLoop._build_messages synthesizes and prepends, and can additionally
# have been shortened by trim_messages_to_budget. When that coordinate-space
# gap cannot be resolved cheaply (see `_resolve_verified_splice_range`), the
# turn is declared non-comparable under this reason rather than splicing at
# the recorded indices and calling the result "exact".
SKIP_REASON_COMPACTION_RANGE_UNVERIFIABLE = "compaction-range-unverifiable"

# Divergence classification reasons (see `classify_divergence`) -- named so
# callers (the report tool included) never hand-type these strings either.
REASON_CONTAINS_TOOL_ROLE = "contains-tool-role"
REASON_UNCLASSIFIED = "unclassified"

# The exact scope every divergence payload and the report tool both state.
COMPARISON_SCOPE = "role+content of non-system messages"

_MAX_DIFF_ENTRIES = 20
_MAX_CONTENT_PREVIEW = 200


class NonComparableDerivation(Exception):
    """Raised when a replayed history/compaction event cannot be faithfully

    reconstructed as a message-list splice -- NOT an integrity violation
    (the log is not corrupt) and NOT a `ValueError`, so it is never
    accidentally swallowed by `SHADOW_EXCEPTIONS`' generic failure path.

    Two distinct, named causes (`reason`, one of the `SKIP_REASON_*`
    constants above), both resolving to "decline, never guess":
    - `reconstruction == "lossy-fallback"` (session_log_events.compaction_payload)
      means the compactor's progressive heuristic-trim fallback dropped
      messages within the recorded range without replacing them 1:1; naively
      splicing `spliced_role`/`spliced_content` over that range would delete
      real, still-present content (built-count-vs-derived-count regression
      the reviewer reproduced).
    - the recorded `replaced_from`/`replaced_to` cannot be verified against
      this fold's own working list (see `_resolve_verified_splice_range`) --
      the conversation-space the compactor recorded indices in and the
      request-space this fold works in are not the same coordinate system in
      general (a synthesized system-message prefix, and/or additional budget
      trimming this fold cannot see into), so applying them unverified would
      silently splice at the wrong position and still call it exact.

    The only honest response to either is to decline: never guess a
    reconstruction, never silently drop the event either.
    """

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


class DerivationIntegrityError(ValueError):
    """Raised when a run's replayed events violate the seq invariants derive_messages relies on.

    Two invariants, deliberately narrow (see the module docstring's honesty
    note on what CAN be enforced): (1) no two events on the same run share a
    seq -- `(run_id, seq)` must be unique on the events this fold walks; (2) a
    model/response's `request_seq` must match some model/request's `seq` in
    the SAME set of events. Neither invariant demands global gapless
    contiguity -- other event types (a chat writer's own text/tool_call
    events) legitimately interleave on the same run and are not seq-adjacent
    to model/request or model/response events.
    """


def _validate_integrity(events: list[dict[str, Any]]) -> None:
    seen_seqs: set[Any] = set()
    request_seqs: set[Any] = set()
    responses: list[dict[str, Any]] = []
    for event in events:
        seq = event.get("seq")
        if seq in seen_seqs:
            raise DerivationIntegrityError(f"duplicate seq {seq!r} within one run's replayed events")
        seen_seqs.add(seq)
        etype = event.get("type")
        if etype == sle.MODEL_REQUEST:
            request_seqs.add(seq)
        elif etype == sle.MODEL_RESPONSE:
            responses.append(event)
    for response in responses:
        req_seq = response.get("request_seq")
        if req_seq not in request_seqs:
            raise DerivationIntegrityError(
                f"model/response request_seq={req_seq!r} matches no model/request in this run"
            )


def _resolve_verified_splice_range(messages: list[dict[str, Any]], event: dict[str, Any]) -> tuple[int, int] | None:
    """Resolve a history/compaction event's replaced_from/replaced_to onto `messages`' own coordinate space, or decline.

    `replaced_from`/`replaced_to` are recorded relative to the CONVERSATION
    the compactor mutated (self._conversation) -- which carries no leading
    system message in production, since AgentLoop synthesizes and prepends
    that separately, only inside `_build_messages`. `messages` here is this
    fold's working list, seeded verbatim from a `model/request` event's
    payload -- the ACTUAL request sent, which does carry that prefix (and
    may additionally have been shortened by `trim_messages_to_budget`, a
    second source of drift this function has no visibility into at all).
    The recorded indices are therefore not directly usable against
    `messages` in general.

    Two candidate offsets are tried, smaller first: 0 (the indices already
    share this list's coordinate space -- true whenever the compactor was
    itself handed a conversation that already carried its own leading system
    message, e.g. `self._conversation` before AgentLoop's synthesis point)
    and `sys_prefix` (the count of leading system-role messages already in
    `messages` -- true in production, where the compactor's conversation has
    none and the request prepends exactly that many). A candidate is
    accepted only when the resulting range stays entirely OUTSIDE the
    leading system-message block and in bounds -- compaction never
    legitimately touches the system prompt, so a candidate that would splice
    into it is proof the offset is wrong, not license to apply it anyway.
    Neither candidate passing means the coordinate space cannot be resolved
    cheaply here; the caller declines rather than guessing.
    """
    replaced_from = int(event.get("replaced_from", 0))
    replaced_to = int(event.get("replaced_to", 0))
    if replaced_from < 0 or replaced_to < replaced_from:
        return None

    sys_prefix = 0
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "system":
            sys_prefix += 1
        else:
            break

    for offset in dict.fromkeys((0, sys_prefix)):  # try 0 first, dedup when sys_prefix == 0
        adj_from = replaced_from + offset
        adj_to = replaced_to + offset
        if adj_from < sys_prefix or adj_to > len(messages) or adj_from > adj_to:
            continue
        candidate_range = messages[adj_from:adj_to]
        if any(isinstance(m, dict) and m.get("role") == "system" for m in candidate_range):
            continue
        return adj_from, adj_to
    return None


def derive_messages(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reconstruct the message list the run's NEXT model/request should contain.

    Pure: no I/O, no mutation of `events` or of anything reachable from it.
    Raises `DerivationIntegrityError` (a `ValueError`) when the seq
    invariants above are violated -- loud, never silently patched over.

    Folds events in seq order:
    - model/request seeds (or re-seeds) the working list from its verbatim
      `messages` -- the ground truth of what a prior request actually sent.
    - model/response appends the assistant turn that followed it (text, plus
      tool_calls when present).
    - history/compaction splices `[replaced_from:replaced_to)` out and
      replaces it with the recorded spliced message -- UNLESS the event's
      `reconstruction` field is `"lossy-fallback"`, OR the recorded range
      cannot be verified against this fold's own working list (see
      `_resolve_verified_splice_range`: the compactor records indices in
      conversation-space, no leading system message, while this fold works
      in request-space, seeded from a captured `model/request` payload that
      DOES carry AgentLoop's synthesized system-message prefix and may
      additionally have been trimmed). Either case raises
      `NonComparableDerivation` rather than guess (see that class).
    - history/truncate cuts the list down to its `kept` length.
    - Any other event type (context/inject, history/fork, history/imported,
      shadow/divergence itself) is not applied -- see the module docstring's
      "Input scope" section for exactly why each is out of scope here.

    Returns `[]` when the events carry no model/request at all (nothing to
    derive from yet) -- callers that need to distinguish "no baseline" from
    "empty conversation" should check for a `model/request` event themselves
    before calling, as `shadow_diff_if_enabled` below does.
    """
    events_list = sorted(events, key=lambda e: (int(e.get("seq") or 0),))
    _validate_integrity(events_list)

    messages: list[dict[str, Any]] = []
    have_baseline = False
    for event in events_list:
        etype = event.get("type")
        if etype == sle.MODEL_REQUEST:
            messages = copy.deepcopy(event.get("messages") or [])
            have_baseline = True
        elif etype == sle.MODEL_RESPONSE:
            if not have_baseline:
                continue
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": event.get("text", "")}
            tool_calls = event.get("tool_calls") or []
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)
        elif etype == sle.HISTORY_COMPACTION:
            if not have_baseline:
                continue
            if event.get("reconstruction") == sle.RECONSTRUCTION_LOSSY_FALLBACK:
                raise NonComparableDerivation(
                    "history/compaction event is reconstruction='lossy-fallback' -- "
                    "the heuristic-trim fallback is not representable as one splice",
                    reason=SKIP_REASON_LOSSY_COMPACTION_FALLBACK,
                )
            resolved_range = _resolve_verified_splice_range(messages, event)
            if resolved_range is None:
                raise NonComparableDerivation(
                    "history/compaction event's replaced_from/replaced_to could not be "
                    "verified against this run's derived message list -- the compactor's "
                    "conversation-space indices and this fold's request-space coordinates "
                    "may not align (a synthesized system-message prefix, or additional "
                    "budget trimming, neither of which this fold can see into) -- "
                    "declining rather than guessing a splice position",
                    reason=SKIP_REASON_COMPACTION_RANGE_UNVERIFIABLE,
                )
            replaced_from, replaced_to = resolved_range
            # Splice the message the compactor ACTUALLY spliced, recorded
            # verbatim on the event (spliced_role/spliced_content) -- never
            # re-derived from summary_text, which is the raw summarization
            # output, not the wrapped/marked message that really landed in
            # the conversation. Re-implementing the compactor's own
            # marker/wrapper format here would drift the moment that format
            # changes; replaying what was recorded cannot.
            spliced_msg = {
                "role": str(event.get("spliced_role", "assistant")),
                "content": str(event.get("spliced_content", event.get("summary_text", ""))),
            }
            messages = messages[:replaced_from] + [spliced_msg] + messages[replaced_to:]
        elif etype == sle.HISTORY_TRUNCATE:
            if not have_baseline:
                continue
            kept = int(event.get("kept", len(messages)))
            messages = messages[:kept]
        # else: out of scope for this run's reconstruction -- see docstring.
    return messages


def _comparable(messages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Non-system messages, role+content only -- the phase-1 comparison scope."""
    out: list[dict[str, Any]] = []
    for m in messages:
        if not isinstance(m, dict) or m.get("role") == "system":
            continue
        out.append({"role": m.get("role"), "content": m.get("content")})
    return out


def _preview(value: Any) -> Any:
    if isinstance(value, str) and len(value) > _MAX_CONTENT_PREVIEW:
        return value[:_MAX_CONTENT_PREVIEW] + f"...({len(value)} chars)"
    return value


def structural_diff(built: list[dict[str, Any]], derived: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compact, index-aligned diff of `built` vs `derived` over the phase-1 comparison scope.

    Returns `[]` when the two lists agree on role+content for every
    non-system message; otherwise one compact entry per differing index
    (missing entries on either side show as `None`).
    """
    built_c = _comparable(built)
    derived_c = _comparable(derived)
    diffs: list[dict[str, Any]] = []
    for i in range(max(len(built_c), len(derived_c))):
        b = built_c[i] if i < len(built_c) else None
        d = derived_c[i] if i < len(derived_c) else None
        if b != d:
            b_out = {"role": b.get("role"), "content": _preview(b.get("content"))} if b is not None else None
            d_out = {"role": d.get("role"), "content": _preview(d.get("content"))} if d is not None else None
            diffs.append({"index": i, "built": b_out, "derived": d_out})
    return diffs


def _has_tool_signal(messages: Iterable[dict[str, Any]]) -> bool:
    return any(isinstance(m, dict) and (m.get("role") == "tool" or m.get("tool_calls")) for m in messages)


def classify_divergence(built: list[dict[str, Any]], derived: list[dict[str, Any]]) -> str:
    """Cheap, heuristic divergence classification -- NOT proof of cause.

    `"contains-tool-role"` flags the single largest known source of
    expected, honest noise in phase 1 (see the module docstring): tool-
    result messages `loop_execution.py` appends directly to
    `self._conversation` are not yet captured as spine events, so any turn
    that used tools predictably diverges for that reason alone. This tag
    lets the report tool separate that expected class from everything
    else. It is a presence check, not a causal proof -- a divergence tagged
    `"contains-tool-role"` might still also carry a real regression, and one
    tagged `"unclassified"` is not automatically a real bug either.
    """
    if _has_tool_signal(built) or _has_tool_signal(derived):
        return REASON_CONTAINS_TOOL_ROLE
    return REASON_UNCLASSIFIED


def _divergence_payload(
    diffs: list[dict[str, Any]], *, built_count: int, derived_count: int, reason: str
) -> dict[str, Any]:
    return {
        "type": SHADOW_DIVERGENCE,
        "comparison_scope": COMPARISON_SCOPE,
        "built_message_count": int(built_count),
        "derived_message_count": int(derived_count),
        "diff_count": len(diffs),
        "diffs": diffs[:_MAX_DIFF_ENTRIES],
        "reason": reason,
    }


def _skip_payload(reason: str, detail: str) -> dict[str, Any]:
    return {"type": SHADOW_SKIP, "comparison_scope": COMPARISON_SCOPE, "reason": reason, "detail": detail}


def _read_shadow_flag() -> bool:
    raw = str(os.environ.get("THOMAS_HONESTY_SHADOW", "")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


# Read once per process, at import time -- see module docstring. Tests that
# need both positions monkeypatch this module attribute directly rather than
# the environment variable, which would have no effect after import.
SHADOW_ENABLED: bool = _read_shadow_flag()

# Named, fixed exception tuple -- the same capture-never-breaks-the-call
# pattern as thomas/core/capture_context.py's CAPTURE_EXCEPTIONS. A shadow
# comparison is diagnostic only; it must never be able to take the real turn
# down with it.
SHADOW_EXCEPTIONS: tuple[type[BaseException], ...] = (
    RuntimeError,
    ValueError,
    TypeError,
    KeyError,
    OSError,
    sqlite3.Error,
    MemoryError,
)

# Visible, never-silent counter for shadow-diff failures -- mirrors
# LLMClient.capture_failures.
shadow_diff_failures: int = 0


def shadow_diff_if_enabled(run_id: str | None, built_messages: list[dict[str, Any]]) -> None:
    """The loop's one shadow-soak call site, meant to be called unconditionally.

    OFF (`SHADOW_ENABLED` False, the default): returns immediately -- no
    run_store call, no `derive_messages` call, no I/O. This is what makes the
    flag's off-position provably zero behavior change.

    ON: replays `run_id`'s events, and -- only if a prior model/request
    exists on this run (otherwise there is no baseline to derive from, and
    this is honestly not a "comparison" at all, not a silent pass) -- derives
    the expected next message list and structurally diffs it against
    `built_messages`. A non-empty diff appends one `shadow/divergence` event
    to the SAME run via `capture_context.append_capture_event`, carrying the
    comparison scope and a compact diff. If derivation raises
    `NonComparableDerivation` (a lossy-fallback compaction in this run's
    history), this appends a `shadow/skip` event instead -- NEVER a false
    divergence, NEVER a silent false match. Never raises: failures are
    counted in `shadow_diff_failures` and logged at debug, per the fail-safe
    pattern every capture-adjacent path in this plan follows.
    """
    global shadow_diff_failures
    if not SHADOW_ENABLED or not run_id:
        return
    try:
        events = list(run_store.stream_replay(run_id))
        if not any(e.get("type") == sle.MODEL_REQUEST for e in events):
            return
        try:
            derived = derive_messages(events)
        except NonComparableDerivation as e:
            capture_context.append_capture_event(run_id, _skip_payload(e.reason, str(e)))
            return
        diffs = structural_diff(built_messages, derived)
        if diffs:
            reason = classify_divergence(built_messages, derived)
            payload = _divergence_payload(
                diffs, built_count=len(built_messages), derived_count=len(derived), reason=reason
            )
            capture_context.append_capture_event(run_id, payload)
    except SHADOW_EXCEPTIONS as e:
        shadow_diff_failures += 1
        log.debug("Shadow diff failed (%s): %s", type(e).__name__, e)
