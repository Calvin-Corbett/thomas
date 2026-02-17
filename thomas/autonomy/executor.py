from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .scheduler import compute_next_run


def _parse_dt(val: Optional[str]) -> Optional[datetime]:
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


@dataclass
class ExecutorOutcome:
    created_job_ids: List[str]
    skipped: List[Dict[str, Any]]


class ExecutorAgent:
    """Turns a validated plan into enqueued child jobs.

    The planner emits a plan with actions[]. Each action becomes a job in the store.

    We apply policy *before* enqueueing, so denied actions are not created (and are
    instead reported as skipped). Actions that require approval are created in the
    `awaiting_approval` state with an approval row created immediately, so the UI can
    show pending approvals without the engine needing to claim the job first.
    """

    def __init__(
        self,
        *,
        store,
        policy,
        parent_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ):
        self.store = store
        self.policy = policy
        self.parent_id = parent_id
        self.session_id = session_id

    def enqueue_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        actions = plan.get("actions") or []
        now = datetime.now(timezone.utc)

        created: List[str] = []
        skipped: List[Dict[str, Any]] = []

        for idx, a in enumerate(actions):
            if not isinstance(a, dict):
                skipped.append({"index": idx, "reason": "action_not_object"})
                continue

            kind = str(a.get("kind") or "").strip()
            name = str(a.get("name") or kind or f"action-{idx}").strip()
            payload = a.get("payload") if isinstance(a.get("payload"), dict) else {}
            risk_class = str(a.get("risk_class") or "medium").strip()
            schedule = a.get("schedule") if isinstance(a.get("schedule"), dict) else None

            # Policy pre-check
            decision = self.policy.decision_for_job(kind=kind, risk_class=risk_class)
            if not decision.allowed:
                skipped.append({"index": idx, "kind": kind, "risk_class": risk_class, "reason": decision.reason})
                continue

            run_at = _parse_dt(a.get("run_at"))
            next_run = run_at
            if next_run is None and schedule is not None:
                next_run = compute_next_run(schedule, now)
            if next_run is None:
                next_run = now

            requires_approval = bool(decision.requires_approval)

            job = self.store.create_job(
                name=name,
                kind=kind,
                payload=payload,
                schedule=schedule,
                next_run_at=next_run,
                risk_class=risk_class,
                requires_approval=requires_approval,
                parent_id=self.parent_id,
                session_id=self.session_id,
            )

            if requires_approval:
                # Create the approval immediately so humans can approve before the job runs.
                action_preview = {
                    "job_id": job.id,
                    "name": job.name,
                    "kind": job.kind,
                    "risk_class": risk_class,
                    "payload_preview": payload,
                }
                self.store.create_approval(job_id=job.id, action=action_preview, risk_class=risk_class)
                self.store.set_job_status(job.id, "awaiting_approval", requires_approval=True, lock_clear=True)

            created.append(job.id)

        return {
            "created_job_ids": created,
            "skipped": skipped,
            "created_count": len(created),
            "skipped_count": len(skipped),
        }
