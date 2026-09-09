"""Shared execution-plan primitives for REPL and web chat plan mode."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

PlanStatus = Literal["draft", "approved", "executing", "done", "rejected"]
PlanStepStatus = Literal["pending", "running", "done", "skipped", "error"]
PlanDecision = Literal["approve", "refine", "reject"]

_PLAN_STATUSES = {"draft", "approved", "executing", "done", "rejected"}
_PLAN_STEP_STATUSES = {"pending", "running", "done", "skipped", "error"}


@dataclass
class PlanStep:
    """A single step within an execution plan."""

    step_id: str
    description: str
    status: PlanStepStatus = "pending"
    result: str = ""


@dataclass
class ExecutionPlan:
    """A structured plan used across REPL and web execution flows."""

    plan_id: str
    task_description: str
    steps: list[PlanStep] = field(default_factory=list)
    status: PlanStatus = "draft"
    created_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    last_result: str = ""
    note: str = ""


def step_status_icon(status_raw: str) -> str:
    status = coerce_step_status(status_raw)
    return {
        "pending": "[ ]",
        "running": "[~]",
        "done": "[x]",
        "skipped": "[-]",
        "error": "[!]",
    }[status]


def coerce_plan_status(status_raw: Any, default: PlanStatus = "draft") -> PlanStatus:
    status = str(status_raw or "").strip().lower()
    if status in _PLAN_STATUSES:
        return status  # type: ignore[return-value]
    return default


def coerce_step_status(status_raw: Any, default: PlanStepStatus = "pending") -> PlanStepStatus:
    status = str(status_raw or "").strip().lower()
    if status in _PLAN_STEP_STATUSES:
        return status  # type: ignore[return-value]
    return default


def default_allowed_decisions(plan: ExecutionPlan | None) -> list[PlanDecision]:
    if plan is None:
        return []
    if coerce_plan_status(plan.status) == "draft":
        return ["approve", "refine", "reject"]
    return []


def new_plan_id(prefix: str = "plan") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def new_step_id(prefix: str = "step") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


def plan_to_payload(plan: ExecutionPlan) -> dict[str, Any]:
    payload = asdict(plan)
    payload["status"] = coerce_plan_status(plan.status)
    payload["steps"] = [
        {
            "step_id": str(step.step_id or new_step_id()),
            "description": str(step.description or "").strip(),
            "status": coerce_step_status(step.status),
            "result": str(step.result or ""),
        }
        for step in plan.steps
    ]
    payload["allowed_decisions"] = default_allowed_decisions(plan)
    return payload


def plan_from_payload(payload_raw: Any) -> ExecutionPlan | None:
    if not isinstance(payload_raw, dict):
        return None
    raw_steps = payload_raw.get("steps")
    steps: list[PlanStep] = []
    if isinstance(raw_steps, list):
        for item in raw_steps:
            if not isinstance(item, dict):
                continue
            description = str(item.get("description") or "").strip()
            if not description:
                continue
            steps.append(
                PlanStep(
                    step_id=str(item.get("step_id") or new_step_id()),
                    description=description,
                    status=coerce_step_status(item.get("status")),
                    result=str(item.get("result") or ""),
                )
            )
    plan_id = str(payload_raw.get("plan_id") or new_plan_id())
    task_description = str(payload_raw.get("task_description") or "").strip()
    if not task_description:
        task_description = "Planned task"
    created_at = float(payload_raw.get("created_at") or time.time())
    finished_at = float(payload_raw.get("finished_at") or 0.0)
    return ExecutionPlan(
        plan_id=plan_id,
        task_description=task_description,
        steps=steps,
        status=coerce_plan_status(payload_raw.get("status")),
        created_at=created_at,
        finished_at=finished_at,
        last_result=str(payload_raw.get("last_result") or ""),
        note=str(payload_raw.get("note") or ""),
    )


def plan_to_markdown(plan: ExecutionPlan) -> str:
    lines = [f"# Plan: {plan.task_description}", ""]
    lines.append(f"**Status:** {coerce_plan_status(plan.status)}  |  **ID:** `{plan.plan_id}`")
    if plan.note:
        lines.extend(["", f"> {plan.note}"])
    lines.append("")
    if not plan.steps:
        lines.append("*(no steps)*")
    else:
        for index, step in enumerate(plan.steps, 1):
            lines.append(f"{index}. {step_status_icon(step.status)} {step.description}")
            if step.result:
                lines.append(f"   > {step.result[:240]}")
    if plan.last_result:
        lines.extend(["", f"**Last result:** {plan.last_result[:300]}"])
    return "\n".join(lines)
