"""Plan mode handler for the Thomas REPL.

Provides an interactive plan-create-review-execute workflow where the user
can ask the agent to create a multi-step plan, review and edit it, then
execute each step.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class PlanStep:
    """A single step within a plan."""

    step_id: str
    description: str
    status: str = "pending"  # pending | running | done | skipped | error
    result: str = ""


@dataclass
class Plan:
    """A structured execution plan."""

    plan_id: str
    task_description: str
    steps: list[PlanStep] = field(default_factory=list)
    status: str = "draft"  # draft | approved | executing | done | rejected
    created_at: float = 0.0
    finished_at: float = 0.0


def plan_to_markdown(plan: Plan) -> str:
    """Render a plan as markdown text."""
    lines = [f"# Plan: {plan.task_description}", ""]
    lines.append(f"**Status:** {plan.status}  |  **ID:** `{plan.plan_id}`")
    lines.append("")
    if not plan.steps:
        lines.append("*(no steps)*")
    else:
        for i, step in enumerate(plan.steps, 1):
            status_icon = {
                "pending": "[ ]",
                "running": "[~]",
                "done": "[x]",
                "skipped": "[-]",
                "error": "[!]",
            }.get(step.status, "[ ]")
            lines.append(f"{i}. {status_icon} {step.description}")
            if step.result:
                lines.append(f"   > {step.result[:200]}")
    return "\n".join(lines)


class PlanStore:
    """Persists plans to a JSON file."""

    def __init__(self, storage_path: Path) -> None:
        self._path = storage_path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _load_all(self) -> dict[str, dict]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_all(self, data: dict[str, dict]) -> None:
        try:
            self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            log.warning("Failed to save plans: %s", exc)

    def save_plan(self, plan: Plan) -> None:
        data = self._load_all()
        data[plan.plan_id] = {
            "plan_id": plan.plan_id,
            "task_description": plan.task_description,
            "status": plan.status,
            "created_at": plan.created_at,
            "finished_at": plan.finished_at,
            "steps": [
                {
                    "step_id": s.step_id,
                    "description": s.description,
                    "status": s.status,
                    "result": s.result,
                }
                for s in plan.steps
            ],
        }
        self._save_all(data)

    def update_status(self, plan_id: str, status: str) -> None:
        data = self._load_all()
        if plan_id in data:
            data[plan_id]["status"] = status
            self._save_all(data)

    def list_plans(self) -> list[Plan]:
        data = self._load_all()
        plans = []
        for entry in data.values():
            steps = [
                PlanStep(
                    step_id=s.get("step_id", ""),
                    description=s.get("description", ""),
                    status=s.get("status", "pending"),
                    result=s.get("result", ""),
                )
                for s in entry.get("steps", [])
            ]
            plans.append(
                Plan(
                    plan_id=entry.get("plan_id", ""),
                    task_description=entry.get("task_description", ""),
                    steps=steps,
                    status=entry.get("status", "draft"),
                    created_at=entry.get("created_at", 0.0),
                    finished_at=entry.get("finished_at", 0.0),
                )
            )
        plans.sort(key=lambda p: p.created_at, reverse=True)
        return plans


class PlanModeHandler:
    """Interactive plan creation and execution for the REPL."""

    def __init__(self, repl: Any) -> None:
        self._repl = repl
        config = repl.config
        store_path = Path(config.memory.root_path) / "plans.json"
        self._store = PlanStore(store_path)
        self.active_plan: Plan | None = None

    def list_plans(self) -> list[Plan]:
        return self._store.list_plans()

    async def create_plan(self, task_description: str) -> Plan:
        """Ask the agent to generate a plan for the given task."""
        plan_id = f"plan-{uuid.uuid4().hex[:8]}"
        plan = Plan(
            plan_id=plan_id,
            task_description=task_description,
            status="draft",
            created_at=time.time(),
        )

        planning_prompt = (
            f"Create a detailed implementation plan for: {task_description}\n\n"
            "Format your response as a numbered list of concrete steps. "
            "Each step should be actionable and specific."
        )

        from thomas.agent.loop import AgentLoop
        from thomas.core.events import EventType
        from thomas.core.token_economy import normalize_token_economy_level

        session_id = str(getattr(self._repl, "_repl_session_id", "") or "repl").strip() or "repl"
        agent = AgentLoop(
            config=self._repl.config,
            llm=self._repl._get_llm(),
            tools=self._repl.tools,
            conversation=list(self._repl._conversation),
            memory=self._repl._memory,
            thread_id=f"{session_id}-{plan_id}",
            autonomy_level=1,  # Low autonomy for planning
            session_id=session_id,
            run_id=plan_id,
        )

        response_parts: list[str] = []
        token_economy = normalize_token_economy_level("optimal")
        async for event in agent.run(planning_prompt, token_economy=token_economy):
            if event.type == EventType.TEXT_DELTA:
                text = str(event.data.get("text") or "")
                if text:
                    response_parts.append(text)
            elif event.type == EventType.AGENT_DONE:
                final = str(event.data.get("text") or "").strip()
                if final:
                    response_parts = [final]

        response = "".join(response_parts).strip()
        plan.steps = _parse_steps_from_response(response)
        self._store.save_plan(plan)
        self.active_plan = plan
        return plan

    async def present_plan(self, plan: Plan) -> str:
        """Present the plan to the user and get their decision.

        Returns ``"approve"``, ``"reject"``, or ``"edit"``.
        """
        from rich.markdown import Markdown
        from rich.panel import Panel

        md_text = plan_to_markdown(plan)
        self._repl._console.print(Panel(Markdown(md_text), title="Plan", border_style="yellow"))

        from prompt_toolkit.formatted_text import HTML

        try:
            choice = await self._repl._prompt_overlay(
                HTML("<prompt>plan</prompt> > "),
                default="approve",
                toolbar_text="approve | edit | reject",
            )
        except (KeyboardInterrupt, EOFError):
            return "reject"

        choice = str(choice or "").strip().lower()
        if choice.startswith("a"):
            return "approve"
        elif choice.startswith("e"):
            return "edit"
        return "reject"

    async def edit_plan(self, plan: Plan) -> str:
        """Let the user edit steps, then re-present for decision."""
        from prompt_toolkit.formatted_text import HTML

        self._repl._console.print("[dim]Edit steps (enter new text, or 'skip' / 'delete'):[/dim]")
        new_steps: list[PlanStep] = []
        for i, step in enumerate(plan.steps, 1):
            self._repl._console.print(f"  Step {i}: {step.description}")
            try:
                edit = await self._repl._prompt_overlay(
                    HTML(f"<prompt>step {i}</prompt> > "),
                    default=step.description,
                )
            except (KeyboardInterrupt, EOFError):
                new_steps.append(step)
                continue
            edit = str(edit or "").strip()
            if edit.lower() == "delete":
                continue
            elif edit.lower() == "skip":
                step.status = "skipped"
                new_steps.append(step)
            elif edit:
                step.description = edit
                new_steps.append(step)
            else:
                new_steps.append(step)
        plan.steps = new_steps
        self._store.save_plan(plan)
        return await self.present_plan(plan)

    async def execute_plan(self, plan: Plan) -> None:
        """Execute each plan step sequentially using the agent."""
        plan.status = "executing"
        self._store.update_status(plan.plan_id, "executing")

        for step in plan.steps:
            if step.status == "skipped":
                continue
            step.status = "running"
            self._repl._console.print(f"[dim]Executing: {step.description}[/dim]")
            try:
                await self._repl._run_agent(step.description)
                step.status = "done"
            except Exception as exc:
                step.status = "error"
                step.result = str(exc)
                self._repl._console.print(f"[red]Step failed: {exc}[/red]")

        plan.status = "done"
        plan.finished_at = time.time()
        self.active_plan = None
        self._store.save_plan(plan)
        self._repl._console.print("[dim]Plan execution complete.[/dim]")


def _parse_steps_from_response(text: str) -> list[PlanStep]:
    """Extract numbered steps from LLM response text."""
    import re

    steps: list[PlanStep] = []
    # Match patterns like "1. Do something" or "- Do something"
    for m in re.finditer(r"(?:^|\n)\s*(?:\d+[\.\)]\s*|[-*]\s+)(.+)", text):
        desc = m.group(1).strip()
        if desc and len(desc) > 3:
            step_id = f"step-{uuid.uuid4().hex[:6]}"
            steps.append(PlanStep(step_id=step_id, description=desc))
    return steps
