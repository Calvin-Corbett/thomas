"""The Exhaustive-effort pipeline (Step 5).

When a task runs at Exhaustive Effort, this orchestrator sequences the full quality
pipeline:

    task manager (classify + analyze)
      -> intent review        (confidence-gated: only when the task is unclear)
      -> staff the crew       (Effort-scaled team from the router)
      -> research + rubric     (what "good" looks like)
      -> crew work
      -> verify + adversarial review  (with a bounded remediation loop)
      -> deliver

The orchestration and decision logic (intent gating, staffing, the remediation
loop) live here and are unit-testable WITHOUT a live model. The heavy stages
(research, crew work, verification, review) are injected callables so they can be
stubbed in tests and supplied by later steps — verification by Step 6, adversarial
review by Step 7. Lighter Effort levels do NOT use this pipeline; they run the
ordinary single worker.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from thomas.core import task_decomposer
from thomas.marketplace.orchestrator import task_router

log = logging.getLogger(__name__)

EmitFn = Callable[[dict[str, Any]], Awaitable[None]]

MAX_REMEDIATIONS = 2


@dataclass
class PipelineContext:
    prompt: str
    effort: str = "exhaustive"
    autonomy_level: int = 4
    task_type: str = ""
    crew: list[tuple[str, Any]] = field(default_factory=list)
    analysis: task_decomposer.TaskAnalysis | None = None
    intent_confirmed: bool = True
    rubric: dict[str, Any] = field(default_factory=dict)
    work_result: str = ""
    verified: bool = False
    review_passed: bool = False
    remediations: int = 0
    result: str = ""
    stages: list[str] = field(default_factory=list)
    aborted: str = ""


async def _stub_research(ctx: PipelineContext) -> dict[str, Any]:
    _ = ctx
    return {"dimensions": ["correctness"], "weights": {"correctness": 1.0}}


async def _stub_work(ctx: PipelineContext) -> str:
    return f"(built deliverable for: {ctx.prompt[:60]})"


async def _stub_verify(ctx: PipelineContext) -> bool:
    _ = ctx
    return True


async def _stub_review(ctx: PipelineContext) -> bool:
    _ = ctx
    return True


async def _auto_confirm_intent(ctx: PipelineContext) -> bool:
    _ = ctx
    return True


class ExhaustivePipeline:
    """Sequences the Exhaustive quality pipeline. Inject stage executors to test or
    to supply the real (model-backed) implementations."""

    def __init__(
        self,
        *,
        emit: EmitFn | None = None,
        research_fn: Callable[[PipelineContext], Awaitable[dict[str, Any]]] | None = None,
        work_fn: Callable[[PipelineContext], Awaitable[str]] | None = None,
        verify_fn: Callable[[PipelineContext], Awaitable[bool]] | None = None,
        review_fn: Callable[[PipelineContext], Awaitable[bool]] | None = None,
        intent_review_fn: Callable[[PipelineContext], Awaitable[bool]] | None = None,
        classify: Callable[[str], task_router.TaskRoute] | None = None,
        assemble: Callable[..., list[tuple[str, Any]]] | None = None,
        analyze: Callable[[str], task_decomposer.TaskAnalysis] | None = None,
    ) -> None:
        self._emit = emit
        self._research = research_fn or _stub_research
        self._work = work_fn or _stub_work
        self._verify = verify_fn or _stub_verify
        self._review = review_fn or _stub_review
        self._intent_review = intent_review_fn or _auto_confirm_intent
        self._classify = classify or task_router.classify_task
        self._assemble = assemble or task_router.assemble_team
        self._analyze = analyze or task_decomposer.analyze_task

    async def _event(self, stage: str, ctx: PipelineContext, **extra: Any) -> None:
        ctx.stages.append(stage)
        if self._emit is not None:
            await self._emit({"type": "pipeline_stage", "stage": stage, "task_type": ctx.task_type, **extra})

    async def run(self, prompt: str, *, effort: str = "exhaustive", autonomy_level: int = 4) -> PipelineContext:
        ctx = PipelineContext(prompt=str(prompt or ""), effort=effort, autonomy_level=autonomy_level)

        # 1. Task manager — classify the task and analyze clarity.
        route = self._classify(ctx.prompt)
        ctx.task_type = route.task_type
        ctx.analysis = self._analyze(ctx.prompt)
        await self._event("task_manager", ctx, clarity=ctx.analysis.clarity_score)

        # 2. Intent review — only when the analysis says the task is unclear.
        if ctx.analysis.needs_intent_review:
            ctx.intent_confirmed = bool(await self._intent_review(ctx))
            await self._event("intent_review", ctx, confirmed=ctx.intent_confirmed)
            if not ctx.intent_confirmed:
                ctx.aborted = "intent_not_confirmed"
                await self._event("aborted", ctx, reason=ctx.aborted)
                return ctx

        # 3. Staff the crew — Effort-scaled team from the router.
        ctx.crew = list(self._assemble(route, ctx.effort, ctx.autonomy_level))
        await self._event("staff_crew", ctx, crew=[bot.name for _spec, bot in ctx.crew])

        # 4. Research -> rubric — establish what "good" looks like.
        ctx.rubric = dict(await self._research(ctx) or {})
        await self._event("research_rubric", ctx, rubric_dimensions=list(ctx.rubric.get("dimensions", [])))

        # 5. Crew does the work.
        ctx.work_result = str(await self._work(ctx) or "")
        await self._event("crew_work", ctx)

        # 6. Verify + adversarial review, with a bounded remediation loop.
        while True:
            ctx.verified = bool(await self._verify(ctx))
            ctx.review_passed = bool(await self._review(ctx))
            await self._event(
                "verify_review",
                ctx,
                verified=ctx.verified,
                review_passed=ctx.review_passed,
                remediation=ctx.remediations,
            )
            if (ctx.verified and ctx.review_passed) or ctx.remediations >= MAX_REMEDIATIONS:
                break
            ctx.remediations += 1
            ctx.work_result = str(await self._work(ctx) or "")  # redo the work with feedback
            await self._event("remediation", ctx, attempt=ctx.remediations)

        # 7. Deliver.
        ctx.result = ctx.work_result
        await self._event("deliver", ctx, verified=ctx.verified, review_passed=ctx.review_passed)
        return ctx
