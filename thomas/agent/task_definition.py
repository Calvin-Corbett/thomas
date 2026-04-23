"""Max-mode task-definition helpers.

This module derives a concrete "what good looks like" contract for task-like
requests before execution starts. The same contract is then reused for UI
rendering and final pass/fail evaluation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from thomas.core.benchmark_lane import resolve_benchmark_repo_root

_TASK_KEYWORD_RE = re.compile(
    r"\b(build|create|make|implement|fix|update|refactor|write|draft|design|test|debug|"
    r"deploy|benchmark|compare|analy(?:z|s)e|investigate|review|ship|run|produce)\b",
    re.IGNORECASE,
)

_INTERACTIVE_KEYWORD_RE = re.compile(
    r"\b(game|ui|page|website|app|dashboard|interface|landing page|interactive|browser|frontend)\b",
    re.IGNORECASE,
)

_PLAN_KEYWORD_RE = re.compile(r"\b(plan|roadmap|milestone|timeline|strategy)\b", re.IGNORECASE)
_ANALYSIS_KEYWORD_RE = re.compile(r"\b(analy(?:z|s)e|compare|review|report|summary|investigate)\b", re.IGNORECASE)
_CODE_KEYWORD_RE = re.compile(r"\b(code|function|script|api|endpoint|repo|repository|test|bug|fix)\b", re.IGNORECASE)
_RELATIVE_PATH_RE = re.compile(r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_. -]+)+$")
_MENTION_LINE_RE = re.compile(r"mention:\s*(?P<path>[A-Za-z0-9_.\-/ ]+)", re.IGNORECASE)


@dataclass(slots=True)
class TaskDefinition:
    task_summary: str
    deliverable_type: str
    good_result_definition: str
    required_outputs: list[str]
    acceptance_checks: list[str]
    visible_success_criteria: list[str]
    failure_conditions: list[str]
    required_artifact_paths: list[str] = field(default_factory=list)
    required_response_mentions: list[str] = field(default_factory=list)
    task_like: bool = True
    interactive: bool = False
    source_prompt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_summary": self.task_summary,
            "deliverable_type": self.deliverable_type,
            "good_result_definition": self.good_result_definition,
            "required_outputs": list(self.required_outputs),
            "acceptance_checks": list(self.acceptance_checks),
            "visible_success_criteria": list(self.visible_success_criteria),
            "failure_conditions": list(self.failure_conditions),
            "required_artifact_paths": list(self.required_artifact_paths),
            "required_response_mentions": list(self.required_response_mentions),
            "task_like": bool(self.task_like),
            "interactive": bool(self.interactive),
            "source_prompt": self.source_prompt,
        }


def _clean_lines(text: str) -> list[str]:
    return [line.strip(" -\t") for line in str(text or "").splitlines() if line.strip()]


def _summarize_prompt(text: str, *, limit: int = 140) -> str:
    collapsed = " ".join(str(text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3].rstrip() + "..."


def _extract_explicit_checks(text: str) -> list[str]:
    checks: list[str] = []
    for raw_line in _clean_lines(text):
        lower = raw_line.lower()
        if raw_line.startswith(("must ", "should ", "need ", "include ", "support ", "provide ")):
            checks.append(raw_line)
            continue
        if lower.startswith(("rules:", "acceptance", "success", "criteria:")):
            continue
        if any(token in lower for token in ("must", "should", "required", "no console errors", "restart", "verify")):
            checks.append(raw_line)
    deduped: list[str] = []
    for item in checks:
        if item not in deduped:
            deduped.append(item)
    return deduped[:8]


def _looks_like_relative_path(value: str) -> bool:
    candidate = str(value or "").strip().strip("`")
    if not candidate:
        return False
    if "\\" in candidate:
        return False
    if candidate.startswith(("/", "./", "../")):
        return False
    return bool(_RELATIVE_PATH_RE.fullmatch(candidate))


def extract_required_artifact_contract(text: str) -> dict[str, list[str]]:
    prompt = str(text or "")
    lines = prompt.splitlines()
    required_paths: list[str] = []
    required_mentions: list[str] = []

    for idx, raw_line in enumerate(lines):
        line = str(raw_line or "").strip()
        lower = line.lower()
        mention_match = _MENTION_LINE_RE.search(line)
        if mention_match is not None:
            candidate = str(mention_match.group("path") or "").strip().strip("`")
            if _looks_like_relative_path(candidate) and candidate not in required_mentions:
                required_mentions.append(candidate)

        if "exact relative path" not in lower:
            continue
        for follow in lines[idx + 1 :]:
            stripped = str(follow or "").strip()
            if not stripped:
                if required_paths:
                    break
                continue
            candidate = stripped.lstrip("-* ").strip().strip("`")
            if _looks_like_relative_path(candidate):
                if candidate not in required_paths:
                    required_paths.append(candidate)
                if candidate not in required_mentions:
                    required_mentions.append(candidate)
                continue
            if required_paths:
                break

    return {
        "required_artifact_paths": required_paths,
        "required_response_mentions": required_mentions,
    }


def evaluate_required_artifact_contract(
    prompt_text: str,
    *,
    response_text: str,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    contract = extract_required_artifact_contract(prompt_text)
    root = Path(repo_root) if repo_root is not None else resolve_benchmark_repo_root() or Path.cwd()
    response_lower = str(response_text or "").lower()

    missing_paths: list[str] = []
    for rel in contract["required_artifact_paths"]:
        if not (root / Path(rel)).exists():
            missing_paths.append(rel)

    missing_mentions: list[str] = []
    for rel in contract["required_response_mentions"]:
        if str(rel).lower() not in response_lower:
            missing_mentions.append(rel)

    return {
        "required_artifact_paths": list(contract["required_artifact_paths"]),
        "required_response_mentions": list(contract["required_response_mentions"]),
        "missing_paths": missing_paths,
        "missing_response_mentions": missing_mentions,
        "repo_root": str(root),
        "passed": not missing_paths and not missing_mentions,
    }


def infer_deliverable_type(text: str) -> tuple[str, bool]:
    prompt = str(text or "")
    interactive = bool(_INTERACTIVE_KEYWORD_RE.search(prompt))
    lower = prompt.lower()
    if "snake game" in lower or ("game" in lower and interactive):
        return "interactive_game", True
    if interactive:
        return "interactive_ui", True
    if _PLAN_KEYWORD_RE.search(prompt):
        return "plan", False
    if _ANALYSIS_KEYWORD_RE.search(prompt):
        return "analysis", False
    if _CODE_KEYWORD_RE.search(prompt):
        return "code_change", False
    return "task_delivery", False


def is_task_like_request(text: str, *, requested_job_type: str | None = None) -> bool:
    prompt = str(text or "").strip()
    if not prompt:
        return False
    job_type = str(requested_job_type or "").strip().lower()
    if job_type in {"benchmark", "coding", "coding_task", "debug_audit", "batch_task"}:
        return True
    if len(prompt.split()) <= 3 and "?" in prompt:
        return False
    return bool(_TASK_KEYWORD_RE.search(prompt))


def should_activate_task_definition(
    *,
    prompt_text: str,
    applied_token_economy: str,
    requested_job_type: str | None = None,
) -> bool:
    return str(applied_token_economy or "").strip().lower() == "max" and is_task_like_request(
        prompt_text,
        requested_job_type=requested_job_type,
    )


def derive_task_definition(text: str) -> TaskDefinition:
    prompt = str(text or "").strip()
    deliverable_type, interactive = infer_deliverable_type(prompt)
    summary = _summarize_prompt(prompt)
    explicit_checks = _extract_explicit_checks(prompt)
    artifact_contract = extract_required_artifact_contract(prompt)

    required_outputs = ["A result that directly satisfies the user request."]
    acceptance_checks = ["The deliverable matches the literal user prompt."]
    visible_success_criteria = ["A reviewer can tell the task succeeded from the actual result, not just a claim."]
    failure_conditions = [
        "The output only partially matches the prompt scope.",
        "The result depends on hidden assumptions or internal-only checks.",
    ]

    if deliverable_type == "interactive_game":
        good_result = (
            "A good interactive game is immediately playable, responsive to controls, "
            "and visibly demonstrates its main loop without requiring hidden test hooks."
        )
        required_outputs = [
            "A playable browser game artifact.",
            "Clear controls and obvious start/restart flow.",
            "Verification evidence that the visible gameplay loop works.",
        ]
        acceptance_checks = [
            "The page loads cleanly with the requested game mechanics.",
            "Core gameplay visibly runs after normal user interaction.",
            "Controls, score/state updates, and failure/restart flow behave as expected.",
        ]
        visible_success_criteria = [
            "After a normal start action, the game visibly advances on screen.",
            "Human-visible playability outranks internal hook correctness.",
            "Do not claim success unless the live behavior was directly verified.",
        ]
        failure_conditions = [
            "The artifact only works through test-only APIs such as manual time advancement.",
            "The game is static, stalled, or only theoretically correct.",
            "The response claims completion without visible verification evidence.",
        ]
    elif deliverable_type == "interactive_ui":
        good_result = (
            "A good interactive UI works for a person using the page directly and prioritizes "
            "visible behavior, clarity, and stability over internal-only correctness."
        )
        required_outputs = [
            "A working interactive UI artifact.",
            "Direct verification of the visible user flow.",
        ]
        acceptance_checks = [
            "The requested interface is present and usable.",
            "Primary actions visibly work in the live UI.",
            "The output does not rely on hidden hooks to appear successful.",
        ]
        visible_success_criteria = [
            "A user can complete the primary flow in the visible UI.",
            "Visible behavior outranks internal-only compliance.",
        ]
        failure_conditions = [
            "The UI only passes internal checks but fails human-visible use.",
            "The response claims success without live verification evidence.",
        ]
    elif deliverable_type == "code_change":
        good_result = (
            "A good code task changes the right files, preserves scope discipline, and includes "
            "credible verification rather than just describing intended changes."
        )
        required_outputs = [
            "Concrete code or artifact changes that match the prompt.",
            "Verification evidence such as tests, runtime checks, or direct inspection.",
        ]
        acceptance_checks = [
            "The implementation addresses the requested task directly.",
            "The response includes what changed and how it was verified.",
            "The result does not quietly narrow the prompt to an easier subtask.",
        ]
        visible_success_criteria = [
            "If the task affects user-facing behavior, the response should note live verification.",
        ]
        failure_conditions = [
            "The response describes a plan but does not deliver the requested change.",
            "Verification is missing, weak, or unrelated to the requested behavior.",
        ]
    elif deliverable_type == "analysis":
        good_result = (
            "A good analysis task is accurate, grounded, comparative when needed, and reaches a clear verdict."
        )
        required_outputs = [
            "A grounded answer or report.",
            "Clear reasoning tied to the requested comparison or analysis.",
        ]
        acceptance_checks = [
            "The answer addresses the specific question asked.",
            "Important claims are supported by evidence from the task context.",
            "The result reaches a practical conclusion, not just observations.",
        ]
        visible_success_criteria = [
            "If the analysis concerns a live artifact, conclusions should match what is actually observable.",
        ]
        failure_conditions = [
            "The answer is vague, hedged, or misses the requested judgment.",
            "The output ignores obvious user-visible evidence.",
        ]
    elif deliverable_type == "plan":
        good_result = "A good plan is concrete, sequenced, and directly executable."
        required_outputs = [
            "A concrete plan with clear next steps.",
            "Acceptance criteria or checkpoints where appropriate.",
        ]
        acceptance_checks = [
            "The plan is tied to the user request, not a generic template.",
            "The plan is sequenced and realistic.",
            "The plan states what success looks like.",
        ]
        visible_success_criteria = [
            "If the plan targets a visible artifact, it should include explicit proof steps.",
        ]
        failure_conditions = [
            "The plan is generic or missing execution checkpoints.",
            "The plan omits what a good final result looks like.",
        ]
    else:
        good_result = (
            "A good task result directly satisfies the prompt, keeps the intended scope, and includes enough "
            "evidence for the user to judge whether it actually worked."
        )

    for item in explicit_checks:
        if item not in acceptance_checks:
            acceptance_checks.append(item)
    for rel_path in artifact_contract["required_artifact_paths"]:
        required_output = f"Write the required artifact to {rel_path}."
        if required_output not in required_outputs:
            required_outputs.append(required_output)
        acceptance_check = f"Required artifact path exists: {rel_path}"
        if acceptance_check not in acceptance_checks:
            acceptance_checks.append(acceptance_check)
    for rel_path in artifact_contract["required_response_mentions"]:
        acceptance_check = f"Final response explicitly mentions: {rel_path}"
        if acceptance_check not in acceptance_checks:
            acceptance_checks.append(acceptance_check)

    return TaskDefinition(
        task_summary=summary or "Complete the requested task.",
        deliverable_type=deliverable_type,
        good_result_definition=good_result,
        required_outputs=required_outputs,
        acceptance_checks=acceptance_checks,
        visible_success_criteria=visible_success_criteria,
        failure_conditions=failure_conditions,
        required_artifact_paths=list(artifact_contract["required_artifact_paths"]),
        required_response_mentions=list(artifact_contract["required_response_mentions"]),
        task_like=True,
        interactive=interactive,
        source_prompt=prompt,
    )


def build_task_definition_prompt(definition_payload: dict[str, Any] | None) -> str:
    if not isinstance(definition_payload, dict) or not definition_payload:
        return ""

    def _render_list(title: str, rows: Any) -> str:
        values = [str(item).strip() for item in (rows or []) if str(item).strip()]
        if not values:
            return ""
        joined = "\n".join(f"- {item}" for item in values)
        return f"{title}\n{joined}\n"

    summary = str(definition_payload.get("task_summary") or "").strip()
    deliverable_type = str(definition_payload.get("deliverable_type") or "").strip()
    good_result = str(definition_payload.get("good_result_definition") or "").strip()
    parts = [
        "[Task Definition Contract]",
        f"Task summary: {summary}" if summary else "",
        f"Deliverable type: {deliverable_type}" if deliverable_type else "",
        f"What a good result looks like: {good_result}" if good_result else "",
        _render_list("Required outputs:", definition_payload.get("required_outputs")),
        _render_list("Acceptance checks:", definition_payload.get("acceptance_checks")),
        _render_list("Required artifact paths:", definition_payload.get("required_artifact_paths")),
        _render_list("Required response mentions:", definition_payload.get("required_response_mentions")),
        _render_list("Visible success criteria:", definition_payload.get("visible_success_criteria")),
        _render_list("Failure conditions:", definition_payload.get("failure_conditions")),
        (
            "Use this contract for planning, execution, and self-checking. "
            "Do not silently narrow the task. For interactive work, visible success outranks internal-only hooks."
        ),
    ]
    return "\n".join(part for part in parts if part).strip()


def augment_prompt_with_task_definition(prompt: Any, definition_payload: dict[str, Any] | None) -> Any:
    contract = build_task_definition_prompt(definition_payload)
    if not contract:
        return prompt
    if isinstance(prompt, str):
        return f"{prompt.rstrip()}\n\n{contract}\n"
    if isinstance(prompt, list):
        updated: list[Any] = []
        inserted = False
        for part in prompt:
            if not inserted and isinstance(part, dict) and part.get("type") == "text":
                updated.append({"type": "text", "text": f"{str(part.get('text') or '').rstrip()}\n\n{contract}\n"})
                inserted = True
                continue
            updated.append(part)
        if not inserted:
            updated.insert(0, {"type": "text", "text": contract})
        return updated
    return prompt


def evaluate_task_result(
    definition_payload: dict[str, Any] | None,
    *,
    response_text: str,
    token_report: dict[str, Any] | None = None,
    run_ok: bool | None = None,
) -> dict[str, Any]:
    definition = dict(definition_payload or {})
    token_report = dict(token_report or {})
    rules = token_report.get("rules_of_road")
    rules_passed = bool(isinstance(rules, dict) and rules.get("passed", False))
    text = str(response_text or "").strip()
    lower = text.lower()
    interactive = bool(definition.get("interactive"))

    passed_checks: list[str] = []
    failed_checks: list[str] = []

    if run_ok is False:
        failed_checks.append("The run ended with an error.")
    else:
        passed_checks.append("The run completed without a terminal execution error.")

    if rules_passed:
        passed_checks.append("Thomas' quality rules passed.")
    else:
        failed_checks.append("Thomas' quality rules did not pass.")

    if text:
        passed_checks.append("A final response was produced.")
    else:
        failed_checks.append("No final response text was produced.")

    artifact_contract = evaluate_required_artifact_contract(
        str(definition.get("source_prompt") or ""),
        response_text=text,
    )
    if artifact_contract["required_artifact_paths"] or artifact_contract["required_response_mentions"]:
        if artifact_contract["passed"]:
            passed_checks.append("Required artifact outputs and response mentions are present.")
        else:
            for rel_path in artifact_contract["missing_paths"]:
                failed_checks.append(f"Required artifact path is missing: {rel_path}")
            for rel_path in artifact_contract["missing_response_mentions"]:
                failed_checks.append(f"Final response does not mention required path: {rel_path}")

    if interactive:
        visible_tokens = (
            "verified",
            "tested",
            "playable",
            "works in browser",
            "opened",
            "loaded",
            "visibly",
            "clicked",
            "start button",
        )
        if any(token in lower for token in visible_tokens):
            passed_checks.append("The response includes visible-behavior verification language.")
        else:
            failed_checks.append("The response lacks visible-behavior verification for an interactive task.")

    verdict = "passed" if not failed_checks else "failed"
    summary = (
        "Task definition passed."
        if verdict == "passed"
        else "Task definition failed: " + "; ".join(failed_checks[:3])
    )
    return {
        "status": verdict,
        "summary": summary,
        "passed_checks": passed_checks,
        "failed_checks": failed_checks,
        "rules_of_road_passed": rules_passed,
        "interactive": interactive,
        "artifact_contract": artifact_contract,
    }


__all__ = [
    "TaskDefinition",
    "augment_prompt_with_task_definition",
    "build_task_definition_prompt",
    "derive_task_definition",
    "evaluate_required_artifact_contract",
    "evaluate_task_result",
    "extract_required_artifact_contract",
    "infer_deliverable_type",
    "is_task_like_request",
    "should_activate_task_definition",
]
