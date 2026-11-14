"""The lock on the door job creation actually uses.

``WorkStore.update_onboarding`` runs a real phase machine -- no phase jumps, a
twelve-character confirmed goal before mapping, a workflow map and an explicit
selection before configuration. Every one of those rules works. They just guard a
route job creation does not take: measured 2026-09-08, a job was created against
an app sitting in ``goal_discovery`` with an empty goal.

Two rules live here, and no copy of anything the phase machine already owns.

1. Onboarding must have reached workflow configuration. Note the shape of the
   real flow before reading this as "must be ready": ``finishOnboarding`` creates
   the job FIRST and builds the workflows afterwards, so a job is legitimately
   created while onboarding state is still ``collecting``. The phase is what
   separates that from the hole -- measured 2026-09-08, a job was created against
   an app still in ``goal_discovery`` with an empty goal.

2. If onboarding actually happened, the workflow selection must sit at a real
   user turn. ``selected_workflow_user_turn`` is set by the browser to the
   user-turn count at the moment of the click, so a marker of zero means no user
   action was ever recorded and a marker past the conversation names a turn that
   never happened.

   The version of this rule in ``update_onboarding`` (now being removed) demanded
   a further user turn *after* the selection. That is deliberately not rescued:
   it rejects a user who chooses and configures in one message, which is a real
   two-turn onboarding. Neither is the four-turn conversation-length rule bundled
   with it -- length cannot establish readiness.

**Which lane ran is always reported.** An app that was never onboarded -- created
directly by a mission or a test -- has no selection to check, so a different lane
applies rather than the same lane quietly excusing itself. A pass whose scope is
invisible is how a gate stops guarding without anyone noticing.

Two escapes, because a wrong gate must never become a dead end: an explicit
``waive_lane`` on the payload (a recorded decision, never silent), and the
``THOMAS_WORK_LANE_GATE`` flag, which the refusal text names.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .gates import GateContext
from .ledger import RunLedger
from .model import Gate, Lane, Step, validate_lane
from .proving import prove_lane

LANE_GATE_FLAG = "THOMAS_WORK_LANE_GATE"
SETTLED_PHASES = ("workflow_configuration", "ready")

MINIMAL_LANE_ID = "work-onboarding-creation"
ENGAGEMENT_LANE_ID = "work-onboarding-creation-engaged"


@dataclass(frozen=True)
class CreationDecision:
    allowed: bool
    lane_id: str = MINIMAL_LANE_ID
    reason: str = ""
    waived: bool = False
    failed_gate_ids: tuple[str, ...] = ()

    def to_metadata(self) -> dict[str, Any]:
        return {"lane_waived": self.waived, "lane_id": self.lane_id, "lane_reason": self.reason}


def gate_enabled() -> bool:
    """On unless explicitly turned off. Absent means on."""

    raw = os.environ.get(LANE_GATE_FLAG)
    if raw is None:
        return True
    return str(raw).strip().lower() not in {"0", "false", "off", "no"}


def _settled_gate() -> Gate:
    return Gate(
        id="onboarding-reached-configuration",
        kind="mechanical",
        description="onboarding got as far as configuring a workflow",
        check="one_of",
        params={"field": "onboarding_phase", "values": list(SETTLED_PHASES)},
        counterexample={"fields": {"onboarding_phase": "goal_discovery"}},
    )


def _engagement_gate() -> Gate:
    return Gate(
        id="selection-sits-at-a-real-turn",
        kind="mechanical",
        description="the workflow selection sits at a turn the user actually took",
        check="marker_within_count",
        params={"field": "user_turns", "marker_field": "selected_workflow_user_turn", "min_marker": 1},
        counterexample={"counters": {"user_turns": 2, "selected_workflow_user_turn": 5}},
    )


def onboarding_creation_lane(lane_id: str = MINIMAL_LANE_ID) -> Lane:
    gates = [_settled_gate()]
    if lane_id == ENGAGEMENT_LANE_ID:
        gates.append(_engagement_gate())
    lane = Lane(
        id=lane_id,
        job_kind=lane_id,
        version=1,
        steps=[Step(id="onboarding_settled", name="Finish onboarding", gates=gates)],
    )
    return prove_lane(validate_lane(lane))


def _user_turns(onboarding: dict[str, Any]) -> int:
    messages = onboarding.get("messages")
    if not isinstance(messages, list):
        return 0
    return sum(1 for row in messages if isinstance(row, dict) and row.get("role") == "user")


def lane_id_for(onboarding: dict[str, Any] | None) -> str:
    """Pick the lane from an observable fact: did an onboarding conversation happen?

    A job created straight through the API by a mission has no selection to check
    and never had one; that is a different situation, not an exemption.
    """

    row = onboarding if isinstance(onboarding, dict) else {}
    return ENGAGEMENT_LANE_ID if _user_turns(row) > 0 else MINIMAL_LANE_ID


def creation_context(onboarding: dict[str, Any] | None) -> GateContext:
    row = onboarding if isinstance(onboarding, dict) else {}
    fields = row.get("fields") if isinstance(row.get("fields"), dict) else {}
    return GateContext(
        fields={
            "onboarding_state": str(row.get("state") or "ready"),
            "onboarding_phase": str(row.get("phase") or "ready"),
        },
        counters={
            "user_turns": _user_turns(row),
            "selected_workflow_user_turn": fields.get("selected_workflow_user_turn"),
        },
    )


def evaluate_creation(
    onboarding: dict[str, Any] | None,
    *,
    payload: dict[str, Any],
) -> tuple[CreationDecision, Lane | None]:
    """Decide, and hand back the lane that was evaluated.

    The lane comes back so the caller can close the run against it -- the gate
    counters live on those gate objects, and without them the evolution loop has
    no evidence to reason from.
    """

    lane_id = lane_id_for(onboarding)
    if not gate_enabled():
        return CreationDecision(allowed=True, lane_id=lane_id, reason=f"{lane_id}: {LANE_GATE_FLAG} is off"), None

    lane = onboarding_creation_lane(lane_id)
    ledger = RunLedger(lane=lane, autonomy_level=2, run_id="creation", attempts_per_step=1)
    outcome = ledger.attempt(creation_context(onboarding))
    if outcome.advanced:
        return CreationDecision(allowed=True, lane_id=lane_id, reason=f"{lane_id}: onboarding is settled"), lane

    failed = tuple(failure.split(":", 1)[0].strip() for failure in outcome.failures)
    detail = "; ".join(outcome.failures) or "onboarding is not settled"
    waive = bool(payload.get("waive_lane")) if isinstance(payload, dict) else False
    if waive:
        return (
            CreationDecision(
                allowed=True,
                lane_id=lane_id,
                waived=True,
                reason=f"{lane_id}: waived by the user: {detail}",
                failed_gate_ids=failed,
            ),
            lane,
        )
    return (
        CreationDecision(
            allowed=False,
            lane_id=lane_id,
            reason=(
                f"{lane_id}: this job's onboarding is not finished ({detail}). Finish it, or send waive_lane to "
                f"create it anyway and record the skip. Set {LANE_GATE_FLAG}=0 to turn this check off entirely."
            ),
            failed_gate_ids=failed,
        ),
        lane,
    )


def creation_decision(onboarding: dict[str, Any] | None, *, payload: dict[str, Any]) -> CreationDecision:
    """Decide whether this job may be created now, and say what was checked."""

    decision, _lane = evaluate_creation(onboarding, payload=payload)
    return decision
