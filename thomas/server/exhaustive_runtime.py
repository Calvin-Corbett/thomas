"""Live wiring for the Exhaustive pipeline.

Constructs an ``ExhaustivePipeline`` whose heavy stages run for real:

  * crew_work -> runs every staffed role as a fresh worker in the isolated
    workspace, streaming tool progress.
  * verify    -> ``verification.verify_deliverable`` (runs ruff over the workspace).
  * review    -> runs three fresh, model-backed adversarial graders through
    correctness, completeness, and robustness lenses.
  * research  -> a lightweight rubric keyed off the task family.

This is what makes ``effort=exhaustive`` actually execute the full quality
pipeline end-to-end instead of a single worker pass. The delegation layer routes
to ``run_exhaustive_pipeline`` when ``is_exhaustive`` is true. Every model pass
must provide a validated runtime receipt, and failed verification or review is a
terminal pipeline failure rather than a deliverable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from statistics import median
from typing import Any

from thomas.core.file_access import READ_ONLY
from thomas.core.token_economy import effective_effort
from thomas.marketplace.orchestrator import adversarial_review, verification
from thomas.marketplace.orchestrator.exhaustive_pipeline import ExhaustivePipeline, PipelineContext
from thomas.server.exhaustive_artifact_evidence import _artifact_evidence
from thomas.server.model_runtime_receipt import validate_model_runtime_receipt
from thomas.server.worker_runtime import run_agent_worker_events

log = logging.getLogger(__name__)


def is_exhaustive(effort: Any, autonomy_level: int = 4) -> bool:
    """True when the coupled Effort level is the top tier (runs the full pipeline)."""
    return effective_effort(effort, autonomy_level) == "max"


_REVIEW_LENSES = ("correctness", "completeness", "robustness")


def _reviewer_runtime_policy(runtime_policy: dict[str, Any] | None) -> dict[str, Any]:
    """Clone a worker policy while reducing reviewer tools to read-only access."""

    reviewer_policy = dict(runtime_policy or {})
    tool_policy = dict(reviewer_policy.get("tools") or {})
    tool_policy.update(
        {
            "allow_shell": False,
            "allow_file_write": False,
            "allow_network": False,
            "allow_browser": False,
            "allow_channels": False,
            "allow_git": False,
        }
    )
    reviewer_policy["tools"] = tool_policy
    return reviewer_policy


class ExhaustiveQualityGateFailure(RuntimeError):
    """The real Max crew ran, but its bounded quality gates did not converge."""


class ExhaustivePassFailure(RuntimeError):
    """Secret-safe attribution for one failed Max model pass."""

    def __init__(self, code: str, *, pass_id: str, role: str, exception_type: str = "") -> None:
        self.code = str(code or "model_pass_failed")
        self.pass_id = str(pass_id or "unknown")
        self.role = str(role or "unknown")
        self.exception_type = str(exception_type or "")
        super().__init__(f"{self.code}: {self.pass_id} ({self.role})")


def _parse_review_result(text: str) -> tuple[float, bool, str]:
    """Parse one grader response; missing or untyped grading fields are a veto."""

    source = str(text or "")
    decoder = json.JSONDecoder()
    for index, char in enumerate(source):
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(source[index:])
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        try:
            score = max(0.0, min(10.0, float(value["score"])))
        except (KeyError, TypeError, ValueError):
            continue
        veto = value.get("veto")
        if not isinstance(veto, bool):
            continue
        reason = str(value.get("reason") or "").strip()[:500]
        return score, veto, reason
    # Models occasionally return JSON-shaped output with unquoted keys or a
    # quoted numeric score. Accept that narrow shape only when all three typed
    # fields are independently present; arbitrary prose still fails closed.
    score_match = re.search(
        r"(?:[\"']score[\"']|\bscore\b)\s*[:=]\s*[\"']?(-?\d+(?:\.\d+)?)",
        source,
        re.IGNORECASE,
    )
    veto_match = re.search(
        r"(?:[\"']veto[\"']|\bveto\b)\s*[:=]\s*(true|false)\b",
        source,
        re.IGNORECASE,
    )
    reason_match = re.search(
        r"(?:[\"']reason[\"']|\breason\b)\s*[:=]\s*([\"'])(.*?)\1",
        source,
        re.IGNORECASE | re.DOTALL,
    )
    if score_match and veto_match and reason_match:
        score = max(0.0, min(10.0, float(score_match.group(1))))
        veto = veto_match.group(1).casefold() == "true"
        reason = reason_match.group(2).strip()[:500]
        return score, veto, reason
    return 0.0, True, "grader returned invalid structured output"


async def run_exhaustive_pipeline(
    app: Any,
    *,
    prompt: str,
    instructions: str,
    work_dir: Any,
    profile: str | None,
    model_id: str | None = None,
    reasoning_effort: str | None = None,
    effort: str,
    specialist_id: str,
    autonomy_level: int = 4,
    file_access: int | None = None,
    guardrails: str = "",
    guardrail_modes: dict[str, str] | None = None,
    job_type: str | None = None,
    work_context_id: str = "",
    memory_enabled: bool = True,
    runtime_policy: dict[str, Any] | None = None,
    task_type: str | None = None,
    crew_specialties: list[str] | tuple[str, ...] | None = None,
    task_analysis: dict[str, Any] | None = None,
    tools_enabled: bool = True,
    tool_evidence_required: bool = False,
    expected_artifacts: list[str] | tuple[str, ...] | None = None,
    emit_stage: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    on_tool: Callable[[str], Awaitable[None]] | None = None,
    on_model_runtime: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    on_quality_review: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> PipelineContext:
    """Run the Exhaustive pipeline with live stage executors; returns the context."""
    work_dir_str = str(work_dir)
    pass_sequence = 0
    task_tools_enabled = bool(tools_enabled)
    expected_artifact_paths = [
        str(value).strip() for value in (expected_artifacts or ()) if isinstance(value, str) and str(value).strip()
    ]
    reviewer_runtime_policy = _reviewer_runtime_policy(runtime_policy)

    async def _model_pass(
        *,
        pass_prompt: str,
        pass_instructions: str,
        role: str,
        agent_name: str,
        pass_kind: str,
        allow_file_access: bool,
    ) -> str:
        nonlocal pass_sequence
        if should_cancel is not None and should_cancel():
            raise asyncio.CancelledError
        pass_sequence += 1
        pass_id = f"max-pass-{pass_sequence}"
        parts: list[str] = []
        model_runtime: dict[str, Any] | None = None
        reviewer_pass = role.startswith("reviewer-")
        try:
            async for event in run_agent_worker_events(
                app,
                prompt=pass_prompt,
                instructions=pass_instructions,
                work_dir=work_dir,
                profile=profile,
                model_id=model_id,
                reasoning_effort=reasoning_effort,
                effort=effort,
                role=role,
                autonomy_level=autonomy_level,
                file_access=READ_ONLY if reviewer_pass else (file_access if allow_file_access else READ_ONLY),
                guardrails=guardrails,
                guardrail_modes=guardrail_modes,
                job_type=job_type,
                work_context_id=work_context_id,
                memory_enabled=memory_enabled,
                tools_enabled=allow_file_access,
                runtime_policy=reviewer_runtime_policy if reviewer_pass else runtime_policy,
            ):
                if should_cancel is not None and should_cancel():
                    raise asyncio.CancelledError
                etype = str(event.get("type") or "")
                if etype == "text":
                    parts.append(str(event.get("text") or ""))
                elif etype == "model_runtime":
                    if model_runtime is not None:
                        raise ExhaustivePassFailure("runtime_receipt_duplicate", pass_id=pass_id, role=role)
                    model_runtime = validate_model_runtime_receipt(
                        event.get("runtime"),
                        requested_profile=str(profile or ""),
                        requested_model_id=str(model_id or ""),
                    )
                    if model_runtime is None:
                        raise ExhaustivePassFailure("runtime_receipt_invalid", pass_id=pass_id, role=role)
                elif etype == "tool_start" and on_tool is not None:
                    await on_tool(str(event.get("name") or "tool"))
                elif etype == "error":
                    raise ExhaustivePassFailure("worker_reported_error", pass_id=pass_id, role=role)
        except asyncio.CancelledError:
            raise
        except ExhaustivePassFailure:
            raise
        except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
            raise ExhaustivePassFailure(
                "worker_runtime_exception",
                pass_id=pass_id,
                role=role,
                exception_type=type(exc).__name__,
            ) from exc
        if model_runtime is None:
            raise ExhaustivePassFailure("runtime_receipt_missing", pass_id=pass_id, role=role)
        if on_model_runtime is not None:
            annotated = dict(model_runtime)
            annotated["pass_kind"] = pass_kind
            annotated["role"] = role
            annotated["agent_name"] = agent_name
            annotated["pass_id"] = pass_id
            await on_model_runtime(annotated)
        return "".join(parts).strip()

    async def _work(ctx: PipelineContext) -> str:
        crew = list(ctx.crew) or [(specialist_id, None)]
        if ctx.remediations:
            lead = crew[:1]
            critics = [member for member in crew[1:] if member[0] == "critic"]
            crew = lead + critics
        results: list[str] = []
        publishable_result = ""
        for role, bot in crew:
            name = str(getattr(bot, "name", "") or role)
            previous = "\n\n".join(filter(None, (str(ctx.work_result or ""), *results)))[-12000:]
            pass_prompt = (
                f"Original user task:\n{prompt}\n\n"
                f"You are {name}, the fresh {role} member of a Max-effort crew. "
                "Do the concrete work appropriate to your role. Use the shared workspace only "
                "when the task needs artifacts or existing workspace evidence; for an answer-only "
                "task, reason in text and do not call file tools. "
                "Improve and verify the actual deliverable; do not merely describe what another agent should do."
            )
            if previous:
                pass_prompt += f"\n\nPrior crew result to audit and improve:\n{previous}"
            result = await _model_pass(
                pass_prompt=pass_prompt,
                pass_instructions=instructions,
                role=role,
                agent_name=name,
                pass_kind="remediation" if ctx.remediations else "crew_work",
                allow_file_access=task_tools_enabled,
            )
            results.append(f"{name} ({role}): {result}")
            publishable_result = result
        # Each specialist receives the preceding draft and must return a complete
        # improved deliverable. The last pass is therefore the crew's publishable
        # candidate; concatenating every intermediate draft would expose review
        # chatter and duplicate answers to the user.
        return publishable_result.strip()

    async def _research(ctx: PipelineContext) -> dict[str, Any]:
        return {
            "dimensions": ["correctness", "completeness", "robustness"],
            "task_type": ctx.task_type,
            "tools_available": task_tools_enabled,
            "tools_required": bool(tool_evidence_required),
        }

    async def _verify(ctx: PipelineContext) -> bool:
        result = verification.verify_deliverable(ctx.task_type, work_dir_str, ctx.work_result)
        checks = tuple(str(check).strip().lower() for check in result.checks)
        passed = bool(result.passed) and not any(check in {"skipped", "error"} for check in checks)
        if expected_artifact_paths:
            artifact_ok, artifacts, artifact_issues = _artifact_evidence(expected_artifact_paths, work_dir_str)
            ctx.rubric["artifact_evidence"] = {
                "passed": artifact_ok,
                "artifacts": artifacts,
                "issues": artifact_issues,
            }
            checks = (*checks, "artifact_readback")
            passed = passed and artifact_ok
        ctx.rubric["verified"] = passed
        ctx.rubric["verification_checks"] = list(checks)
        return passed

    async def _review(ctx: PipelineContext) -> bool:
        scores: list[float] = []
        vetoes: list[bool] = []
        reviews: list[dict[str, Any]] = []
        artifact_rows = (ctx.rubric.get("artifact_evidence") or {}).get("artifacts", [])
        for lens in _REVIEW_LENSES:
            review_prompt = (
                f"Original user task:\n{prompt}\n\n"
                f"Rubric:\n{json.dumps(ctx.rubric, sort_keys=True)}\n\n"
                f"Candidate result:\n{str(ctx.work_result or '')[-16000:]}\n\n"
                f"Workspace artifacts:\n{json.dumps(artifact_rows)}\n\n"
                f"Act as a fresh adversarial grader for the {lens} lens. "
                + (
                    "Use fs.list_dir and fs.read_file to inspect the named artifacts and their supporting data. "
                    "Work read-only and grade the deliverables themselves, not the worker narrative. "
                    if artifact_rows
                    else "This is answer-only; do not call tools. "
                )
                + "Return exactly one compact JSON object: "
                '{"score": 0-10, "veto": true|false, "reason": "evidence in 12 words or fewer"}. '
                "Keep the entire response under 160 characters and close the JSON object before stopping."
            )
            output = await _model_pass(
                pass_prompt=review_prompt,
                pass_instructions="Grade independently. Never trust prior graders or make workspace changes.",
                role=f"reviewer-{lens}",
                agent_name=f"Fresh {lens} grader",
                pass_kind="adversarial_review",
                allow_file_access=bool(artifact_rows),
            )
            score, veto, reason = _parse_review_result(output)
            scores.append(score)
            vetoes.append(veto)
            reviews.append({"lens": lens, "score": score, "veto": veto, "reason": reason})
        median_score = float(median(scores)) if scores else 0.0
        passed = (
            bool(scores)
            and median_score >= adversarial_review.PASS_THRESHOLD
            and not any(vetoes)
            and not any(score < adversarial_review.VETO_THRESHOLD for score in scores)
        )
        ctx.rubric["adversarial_review"] = {
            "median_score": median_score,
            "passed": passed,
            "reviews": reviews,
        }
        if on_quality_review is not None:
            await on_quality_review(
                {
                    "cycle": int(ctx.remediations),
                    "median_score": median_score,
                    "passed": passed,
                    "reviews": reviews,
                }
            )
        return passed

    pipeline = ExhaustivePipeline(
        emit=emit_stage,
        work_fn=_work,
        research_fn=_research,
        verify_fn=_verify,
        review_fn=_review,
        # Intent review auto-confirms in the background (no interactive user); the
        # stage still emits so the chat shows the check happened.
    )
    ctx = await pipeline.run(
        prompt,
        effort=effort,
        autonomy_level=autonomy_level,
        task_type=task_type,
        lead_specialty=specialist_id,
        crew_specialties=crew_specialties,
        task_analysis=task_analysis,
    )
    if not ctx.aborted and not (ctx.verified and ctx.review_passed):
        raise ExhaustiveQualityGateFailure("exhaustive quality gates failed after bounded remediation")
    return ctx
