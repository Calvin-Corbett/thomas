"""The three funnel stages, orchestrating one-shot lanes + pure synthesis.

- DEFINITION: reverse funnel — N isolated lanes, NO scoring, NO elimination; a
  single synthesizer unions every distinct facet and surfaces contradictions.
- RUBRIC: scored funnel — N lanes -> adversarial reviewer scores -> attrition to
  survivors -> union -> acceptance checks.
- PRODUCT: scored funnel — N plan lanes -> reviewer scores -> attrition ->
  simplification (safe cuts only) -> union -> one enriched plan for the builder.

Every model interaction goes through an injected ``ModelCall`` so the whole thing
is unit-testable with canned lanes. Lanes run concurrently (separate calls =
isolation). A ``CallBudget`` caps total model calls per goal.
"""

from __future__ import annotations

import concurrent.futures as cf
import logging
from dataclasses import dataclass, field
from typing import Any

from .evolve_funnel_roles import (
    SYS_DEFINITION_LANE,
    SYS_PRODUCT_LANE,
    SYS_REVIEWER,
    SYS_RUBRIC_LANE,
    SYS_SIMPLIFY,
    SYS_SYNTH_UNION,
    ModelCall,
    anonymize,
    detect_injection_markers,
    parse_items,
    parse_json_block,
)
from .evolve_funnel_synthesis import (
    ScoredArtifact,
    apply_simplification,
    minority_facets,
    pick_survivors,
    render_items,
    reverse_no_scoring_violations,
    union_items,
)

log = logging.getLogger(__name__)


@dataclass
class CallBudget:
    """Hard ceiling on model calls per goal (cost backstop). Fail-open to truncation."""

    limit: int
    used: int = 0
    truncated: bool = False

    def take(self, n: int = 1) -> bool:
        if self.used + n > self.limit:
            self.truncated = True
            return False
        self.used += n
        return True


@dataclass
class StageResult:
    name: str
    text: str = ""
    items: list[dict[str, Any]] = field(default_factory=list)
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    convergence: list[dict[str, Any]] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "text": self.text,
            "items": self.items,
            "contradictions": self.contradictions,
            "convergence": self.convergence,
            **self.detail,
        }


def _run_lanes(
    model_call: ModelCall,
    system: str,
    user: str,
    profile: str,
    n: int,
    budget: CallBudget,
    max_workers: int = 5,
) -> list[str]:
    """Run ``n`` isolated lanes concurrently; drop any that error or are over budget."""
    runnable = 0
    for _ in range(max(1, n)):
        if budget.take(1):
            runnable += 1
        else:
            break
    if runnable == 0:
        return []

    def _one(_i: int) -> str:
        try:
            return model_call(system, user, profile)
        # A dead lane must not kill the stage -- the survivors still synthesise.
        # ``model_call`` is injected: the real adapter can fail on the transport
        # (OSError), on client/config guards (RuntimeError, ImportError), on an
        # unknown profile (KeyError) or on a mis-shaped response (AttributeError,
        # TypeError, ValueError -- which covers json.JSONDecodeError). Returning ""
        # drops the lane, which _run_lanes already filters out.
        except (AttributeError, ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
            log.debug("funnel lane failed (dropped): %s", exc)
            return ""

    with cf.ThreadPoolExecutor(max_workers=min(max_workers, runnable)) as ex:
        return [r for r in ex.map(_one, range(runnable)) if r]


def _score(
    model_call: ModelCall, artifact: str, goal: str, rubric: str, profile: str, budget: CallBudget
) -> ScoredArtifact:
    if not budget.take(1):
        return ScoredArtifact(index=0, artifact=artifact, score=0.5, passed=True, detail={"budget": "truncated"})
    rubric_block = f"\n\nRUBRIC:\n{rubric}" if rubric else ""
    user = f"GOAL:\n{goal}{rubric_block}\n\n" + anonymize(artifact, "Review against the rubric")
    obj = parse_json_block(model_call(SYS_REVIEWER, user, profile)) or {}
    try:
        score = float(obj.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    return ScoredArtifact(
        index=0,
        artifact=artifact,
        score=max(0.0, min(1.0, score)),
        passed=bool(obj.get("pass", score >= 0.5)),
        detail={"weaknesses": obj.get("weaknesses", []), "reason": obj.get("reason", "")},
    )


def _synthesize_union(model_call: ModelCall, body: str, profile: str, budget: CallBudget) -> dict[str, Any]:
    if not budget.take(1):
        return {"merged": body, "contradictions": [], "dropped": [], "budget": "truncated"}
    user = anonymize(body, "Synthesize")
    return parse_json_block(model_call(SYS_SYNTH_UNION, user, profile)) or {"merged": body}


def run_definition_stage(
    goal: str, *, lanes: int, model_call: ModelCall, profile: str, budget: CallBudget
) -> StageResult:
    """Reverse funnel: union the lanes' readings of success; no scoring, no drops."""
    user = f"GOAL:\n{goal}\n\nProduce your independent reading of what success means for this goal."
    raw = _run_lanes(model_call, SYS_DEFINITION_LANE, user, profile, lanes, budget)
    # Source-separation: scan untrusted lane outputs for prompt-injection/gate-bypass
    # markers and SURFACE them as evidence (never silently dropped). (Detector function
    # built by Claude Code via a Thomas-evolve dispatch; wired in here by the watcher.)
    injection_flagged = [{"lane": i, "markers": m} for i, r in enumerate(raw) if (m := detect_injection_markers(r))]
    unioned = union_items([parse_items(r) for r in raw])
    body = render_items(unioned, header="Candidate success facets (each produced independently by an AI):")
    synth = _synthesize_union(model_call, body, profile, budget)

    # Anti-consensus: single-lane facets are preserved AND surfaced prominently so a
    # real requirement seen by only one lane is never lost to frequency. (This + the
    # no-scoring conformance check were designed by the funnel's own self-improvement run.)
    minority = minority_facets(unioned)
    text = str(synth.get("merged") or body)
    if minority:
        text += "\n\n## Minority (single-lane) requirements — preserve, do not drop by frequency:\n" + render_items(
            minority
        )
    conformance = reverse_no_scoring_violations(synth)
    return StageResult(
        name="definition",
        text=text,
        items=[u.to_dict() for u in unioned],
        contradictions=list(synth.get("contradictions") or []),
        convergence=[u.to_dict() for u in unioned if u.convergence > 1],
        detail={
            "dropped": list(synth.get("dropped") or []),
            "minority_facets": [u.to_dict() for u in minority],
            "reverse_conformance": {"ok": not conformance, "violations": conformance},
            "injection_flagged": injection_flagged,
        },
    )


def _scored_union_stage(
    name: str,
    goal: str,
    context: str,
    lane_system: str,
    user_intro: str,
    *,
    lanes: int,
    survivors: int,
    model_call: ModelCall,
    profile: str,
    budget: CallBudget,
    rubric_for_scoring: str = "",
) -> tuple[StageResult, list[str]]:
    """Shared scored funnel: lanes -> score -> attrition -> union. Returns (result, survivor_texts)."""
    user = f"GOAL:\n{goal}\n{context}\n\n{user_intro}"
    raw = _run_lanes(model_call, lane_system, user, profile, lanes, budget)
    if not raw:
        return StageResult(name=name, text=context), []
    scored: list[ScoredArtifact] = []
    for i, art in enumerate(raw):
        s = _score(model_call, art, goal, rubric_for_scoring, profile, budget)
        s.index = i
        scored.append(s)
    kept = pick_survivors(scored, survivors)
    survivor_texts = [str(s.artifact) for s in kept]
    body = "\n\n".join(f"----- ARTIFACT {i + 1} -----\n{t}" for i, t in enumerate(survivor_texts))
    synth = _synthesize_union(model_call, body, profile, budget)
    merged_items = union_items([parse_items(t) for t in survivor_texts])
    return (
        StageResult(
            name=name,
            text=str(synth.get("merged") or body),
            items=[u.to_dict() for u in merged_items],
            contradictions=list(synth.get("contradictions") or []),
            detail={"survivors": len(kept), "lanes_run": len(raw)},
        ),
        survivor_texts,
    )


def run_rubric_stage(
    goal: str, definition: str, *, lanes: int, survivors: int, model_call: ModelCall, profile: str, budget: CallBudget
) -> tuple[StageResult, list[str]]:
    """Scored funnel: derive verification checks from the definition; return acceptance checks."""
    result, survivor_texts = _scored_union_stage(
        "rubric",
        goal,
        context=f"DEFINITION OF SUCCESS:\n{definition}",
        lane_system=SYS_RUBRIC_LANE,
        user_intro="Produce the checks that would prove this definition is met.",
        lanes=lanes,
        survivors=survivors,
        model_call=model_call,
        profile=profile,
        budget=budget,
    )
    # Acceptance checks = union of survivors' check texts (prefer how_to_test commands).
    checks: list[str] = []
    seen: set[str] = set()
    for t in survivor_texts:
        for it in parse_items(t):
            text = str(it.get("how_to_test") or it.get("text") or "").strip()
            if text and text.lower() not in seen:
                checks.append(text)
                seen.add(text.lower())
    result.detail["acceptance_checks"] = checks
    return result, checks


def run_product_stage(
    goal: str,
    definition: str,
    rubric_text: str,
    *,
    lanes: int,
    survivors: int,
    simplification: bool,
    model_call: ModelCall,
    profile: str,
    budget: CallBudget,
) -> StageResult:
    """Scored funnel: converge an implementation PLAN (text), simplification-guarded."""
    result, survivor_texts = _scored_union_stage(
        "product",
        goal,
        context=f"DEFINITION OF SUCCESS:\n{definition}\n\nRUBRIC:\n{rubric_text}",
        lane_system=SYS_PRODUCT_LANE,
        user_intro="Produce the implementation plan that satisfies the definition and rubric.",
        lanes=lanes,
        survivors=survivors,
        model_call=model_call,
        profile=profile,
        budget=budget,
        rubric_for_scoring=rubric_text,
    )
    # Simplification: a deletion lane proposes cuts; only SAFE cuts (nothing
    # load-bearing lost) are applied to the unioned plan elements.
    plan_items = union_items([parse_items(t) for t in survivor_texts])
    plan_item_dicts = [u.to_dict() for u in plan_items]
    if simplification and plan_item_dicts and budget.take(1):
        cut_user = anonymize(render_items(plan_items, "Plan elements:"), "Find safe cuts in")
        cuts = (parse_json_block(model_call(SYS_SIMPLIFY, cut_user, profile)) or {}).get("cuts", [])
        kept, accepted = apply_simplification(plan_item_dicts, cuts)
        result.items = kept
        result.detail["simplification_cuts_accepted"] = accepted
    else:
        result.items = plan_item_dicts
        result.detail["simplification_cuts_accepted"] = []
    return result
