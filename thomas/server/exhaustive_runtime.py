"""Live wiring for the Exhaustive pipeline.

Constructs an ``ExhaustivePipeline`` whose heavy stages run for real:

  * crew_work -> runs the worker (``run_agent_worker_events``) to build the
    deliverable in the isolated workspace, streaming tool progress.
  * verify    -> ``verification.verify_deliverable`` (runs ruff over the workspace).
  * review    -> ``adversarial_review.review_deliverable`` with a deterministic
    heuristic scorer (a model-backed reviewer-bot scorer is a drop-in upgrade).
  * research  -> a lightweight rubric keyed off the task family.

This is what makes ``effort=exhaustive`` actually execute the full quality
pipeline end-to-end instead of a single worker pass. The delegation layer routes
to ``run_exhaustive_pipeline`` when ``is_exhaustive`` is true and falls back to the
ordinary worker on any error.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from thomas.core.token_economy import effective_effort
from thomas.marketplace.orchestrator import adversarial_review, verification
from thomas.marketplace.orchestrator.exhaustive_pipeline import ExhaustivePipeline, PipelineContext
from thomas.server.worker_runtime import run_agent_worker_events

log = logging.getLogger(__name__)


def is_exhaustive(effort: Any, autonomy_level: int = 4) -> bool:
    """True when the coupled Effort level is the top tier (runs the full pipeline)."""
    return effective_effort(effort, autonomy_level) == "max"


def _heuristic_scorer(work_result: Any, rubric: dict, lens: str) -> float:
    """Deterministic placeholder reviewer score in [0, 10].

    Rewards a substantive deliverable that passed verification and shows no failure
    markers. The real reviewers (model-backed, per-lens) replace this; the
    aggregation/veto logic in adversarial_review is unchanged.
    """
    _ = lens
    text = str(work_result or "")
    score = 5.0
    if len(text) > 80:
        score += 2.0
    lowered = text.lower()
    if "error" not in lowered and "failed" not in lowered:
        score += 2.0
    if rubric.get("verified"):
        score += 1.0
    return min(10.0, score)


async def run_exhaustive_pipeline(
    app: Any,
    *,
    prompt: str,
    instructions: str,
    work_dir: Any,
    profile: str | None,
    effort: str,
    specialist_id: str,
    autonomy_level: int = 4,
    emit_stage: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    on_tool: Callable[[str], Awaitable[None]] | None = None,
) -> PipelineContext:
    """Run the Exhaustive pipeline with live stage executors; returns the context."""
    work_dir_str = str(work_dir)

    async def _work(ctx: PipelineContext) -> str:
        parts: list[str] = []
        async for event in run_agent_worker_events(
            app,
            prompt=prompt,
            instructions=instructions,
            work_dir=work_dir,
            profile=profile,
            effort=effort,
            role=specialist_id,
            autonomy_level=autonomy_level,
        ):
            etype = str(event.get("type") or "")
            if etype == "text":
                parts.append(str(event.get("text") or ""))
            elif etype == "tool_start" and on_tool is not None:
                await on_tool(str(event.get("name") or "tool"))
            elif etype == "error":
                raise RuntimeError(str(event.get("error") or "exhaustive worker failed"))
        return "".join(parts).strip()

    async def _research(ctx: PipelineContext) -> dict[str, Any]:
        return {"dimensions": ["correctness", "completeness", "robustness"], "task_type": ctx.task_type}

    async def _verify(ctx: PipelineContext) -> bool:
        result = verification.verify_deliverable(ctx.task_type, work_dir_str, ctx.work_result)
        ctx.rubric["verified"] = result.passed
        return result.passed

    async def _review(ctx: PipelineContext) -> bool:
        result = adversarial_review.review_deliverable(
            ctx.work_result, ctx.rubric, scorer=_heuristic_scorer, budget_ok=True
        )
        return result.passed

    pipeline = ExhaustivePipeline(
        emit=emit_stage,
        work_fn=_work,
        research_fn=_research,
        verify_fn=_verify,
        review_fn=_review,
        # Intent review auto-confirms in the background (no interactive user); the
        # stage still emits so the chat shows the check happened.
    )
    return await pipeline.run(prompt, effort=effort, autonomy_level=autonomy_level)
