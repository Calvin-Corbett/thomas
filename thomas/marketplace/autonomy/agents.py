from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .adapters import ChatAdapter


class PlanValidationError(ValueError):
    pass


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise PlanValidationError(msg)


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Strictly validate a planner output.

    Expected shape:
    {
      "actions": [
        {
          "name": "...",
          "kind": "reminder|daily_briefing|autonomy_task|...",
          "payload": {...},
          "risk_class": "low|medium|high|critical",
          "schedule": null|{...},
          "run_at": null|"ISO-8601"
        }
      ],
      "notes": "optional"
    }
    """
    _require(isinstance(plan, dict), "plan must be an object")
    actions = plan.get("actions")
    _require(isinstance(actions, list) and len(actions) > 0, "plan.actions must be a non-empty array")
    for i, a in enumerate(actions):
        _require(isinstance(a, dict), f"action[{i}] must be an object")
        _require(isinstance(a.get("kind"), str) and a["kind"].strip(), f"action[{i}].kind required")
        _require(isinstance(a.get("name", ""), str), f"action[{i}].name must be string")
        rc = a.get("risk_class", "medium")
        _require(rc in ("low", "medium", "high", "critical"), f"action[{i}].risk_class invalid")
        payload = a.get("payload", {})
        _require(isinstance(payload, dict), f"action[{i}].payload must be object")
        sch = a.get("schedule", None)
        _require(sch is None or isinstance(sch, dict), f"action[{i}].schedule must be object or null")
        run_at = a.get("run_at", None)
        _require(run_at is None or isinstance(run_at, str), f"action[{i}].run_at must be ISO string or null")
    notes = plan.get("notes", "")
    _require(notes is None or isinstance(notes, str), "plan.notes must be string or null")
    return plan


@dataclass
class PlannerPrompts:
    system: str
    user_template: str


DEFAULT_PLANNER_PROMPTS = PlannerPrompts(
    system=(
        "You are Thomas Autonomy Planner. Produce a STRICT JSON object. "
        "You MUST follow the provided schema. "
        "Prefer low-risk actions. "
        "If unsure, create a single 'reminder' action asking the user for clarification."
    ),
    user_template=(
        "Goal:\n{goal}\n\n"
        "Context (optional):\n{context}\n\n"
        "Return JSON with keys: actions (array), notes (string). "
        "Each action must include: name, kind, payload, risk_class, schedule (or null), run_at (or null)."
    ),
)


class PlannerAgent:
    def __init__(self, chat: ChatAdapter, prompts: PlannerPrompts = DEFAULT_PLANNER_PROMPTS):
        self.chat = chat
        self.prompts = prompts

    async def plan(self, *, goal: str, context: str = "", session_id: str | None = None) -> dict[str, Any]:
        schema_hint = {
            "type": "object",
            "required": ["actions"],
            "properties": {
                "actions": {"type": "array"},
                "notes": {"type": "string"},
            },
        }
        user = self.prompts.user_template.format(goal=goal, context=context or "")
        out = await self.chat.generate_json(
            system=self.prompts.system, user=user, schema_hint=schema_hint, session_id=session_id
        )
        if not isinstance(out, dict):
            raise PlanValidationError("planner output is not an object")
        return validate_plan(out)


class ReviewerAgent:
    """Deterministic reviewer: sanity checks the plan and flags risk.

    This is intentionally non-LLM to keep the safety gate simple and inspectable.
    """

    def review(self, plan: dict[str, Any]) -> tuple[bool, list[str]]:
        problems: list[str] = []
        actions = plan.get("actions") or []
        for a in actions:
            rc = a.get("risk_class", "medium")
            kind = a.get("kind", "")
            if rc in ("high", "critical"):
                problems.append(f"Action '{kind}' is {rc} risk; default policy usually denies it.")
            if kind in ("shell", "exec", "filesystem_write", "network_request"):
                problems.append(
                    f"Action kind '{kind}' is potentially dangerous; route via Guardrails and require approval."
                )
        ok = len(problems) == 0
        return ok, problems
