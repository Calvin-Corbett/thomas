"""Funnel evolve engine: a drop-in ``session_runner`` variant for the evolve loop.

The funnel converges a goal through isolated, naive, one-shot agents
(definition -> rubric -> product), hands ONE enriched plan + derived acceptance
checks to the existing green-mirror builder (``run_evolve_session`` — the single
memory-bearing agent), then runs a genuinely independent, cross-family external
evaluator on the result. Every agent except the builder is fresh / one-shot /
memoryless and Thomas-blind: each handoff says only "an AI made this".

This module is ADDITIVE. It NEVER calls the blue-owned promotion gate; it only
produces a (better) session dict for the existing loop + gate to judge. The
external evaluator is advisory and FAIL-CLOSED-ONLY: it may demote the funnel's
own output (make promotion harder), never weaken the gate. Any internal score is
labeled ``unaudited_runtime_self_assessment`` and is never the headline.

If anything in the funnel fails (no provider, bad config, stage error) it falls
back to the classic builder so the loop never breaks.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .evolve_funnel_config import FunnelConfig, load_funnel_config
from .evolve_funnel_families import family_of, lane_families, select_independent_evaluator
from .evolve_funnel_roles import (
    SYS_EVALUATOR,
    DefaultModelCall,
    ModelCall,
    anonymize,
    parse_json_block,
)
from .evolve_funnel_stages import (
    CallBudget,
    run_definition_stage,
    run_product_stage,
    run_rubric_stage,
)

BuilderFn = Callable[..., dict[str, Any]]
ModelInfo = Callable[[str], "tuple[str, str]"]


def _default_builder() -> BuilderFn:
    from .evolve import run_evolve_session

    return run_evolve_session


def _default_model_info(root: Path) -> ModelInfo:
    def info(profile: str) -> tuple[str, str]:
        from thomas.core.config import load_config

        cfg = load_config(Path(root) / "thomas.toml")
        mc = cfg.get_model(profile or None)
        return str(getattr(mc, "provider", "")), str(getattr(mc, "model", ""))

    return info


def _summarize_result(session: dict[str, Any]) -> str:
    changed = session.get("changed_files") or []
    verification = session.get("verification") or []
    ver_lines = []
    for v in verification[:8]:
        if isinstance(v, dict):
            ver_lines.append(f"  - {v.get('command', v.get('name', '?'))}: ok={v.get('ok')}")
    diff = ""
    diff_path = session.get("diff_path")
    if diff_path:
        try:
            diff = Path(diff_path).read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            diff = ""
    return (
        f"Status: {session.get('status')}\n"
        f"Changed files ({len(changed)}): {list(changed)[:40]}\n"
        f"Verification:\n" + ("\n".join(ver_lines) or "  (none)") + "\n"
        f"Diff (truncated):\n{diff}"
    )


def _run_external_evaluator(
    *,
    original_goal: str,
    session: dict[str, Any],
    cfg: FunnelConfig,
    model_call: ModelCall,
    model_info: ModelInfo,
    lane_profile: str,
) -> dict[str, Any]:
    """Cross-family adversarial check on the final result vs the ORIGINAL goal only."""
    used = lane_families([lane_profile] if lane_profile else [], model_info)
    eval_profile, fam, degraded = select_independent_evaluator(cfg.evaluator_candidates, used, model_info)
    check: dict[str, Any] = {
        "independent": not degraded,
        "degraded_reason": "" if not degraded else "no candidate model family disjoint from the lanes",
        "evaluator_profile": eval_profile or "",
        "evaluator_family": fam,
        "lane_families": sorted(used),
        "applied_self_veto": False,
    }
    try:
        # Degraded mode still runs (useful signal) but is labeled not-independent and never self-vetoes.
        profile_for_eval = eval_profile or lane_profile
        user = f"GOAL:\n{original_goal}\n\n" + anonymize(
            _summarize_result(session), "Adversarially try to break this result against the goal"
        )
        obj = parse_json_block(model_call(SYS_EVALUATOR, user, profile_for_eval)) or {}
        check.update(
            verdict=str(obj.get("verdict", "")) or ("fail" if obj.get("broke_it") else "pass"),
            broke_it=bool(obj.get("broke_it", False)),
            findings=list(obj.get("findings") or []),
            reason=str(obj.get("reason", "")),
        )
    except Exception as exc:  # noqa: BLE001 - evaluator failure must not crash the run
        check.update(verdict="error", broke_it=False, findings=[], reason=f"evaluator error: {exc}")
    return check


def run_funnel_session(
    project_root: Path | None = None,
    *,
    goal: str = "",
    profile: str = "",
    passes: int | None = None,
    promote_on_pass: bool = False,
    timeout_seconds: int = 1800,
    refactor_first: bool = True,
    acceptance_checks: list[str] | tuple[str, ...] | None = None,
    builder: BuilderFn | None = None,
    model_call: ModelCall | None = None,
    model_info: ModelInfo | None = None,
    funnel_config: FunnelConfig | None = None,
) -> dict[str, Any]:
    """Run one goal through the funnel; return a session dict (drop-in for run_evolve_session)."""
    root = Path(project_root) if project_root is not None else Path.cwd()
    build = builder or _default_builder()
    cfg = funnel_config or load_funnel_config(root)
    lane_profile = cfg.lane_profile or profile

    def _classic(extra_checks: list[str] | None, funnel_meta: dict[str, Any] | None) -> dict[str, Any]:
        merged_checks = list(acceptance_checks or [])
        if extra_checks:
            merged_checks.extend(c for c in extra_checks if c not in merged_checks)
        out = build(
            root,
            goal=goal,
            profile=profile,
            passes=passes,
            promote_on_pass=promote_on_pass,
            timeout_seconds=timeout_seconds,
            refactor_first=refactor_first,
            acceptance_checks=merged_checks or None,
        )
        if funnel_meta is not None and isinstance(out.get("session"), dict):
            out["session"]["funnel"] = funnel_meta
        return out

    # If the funnel cannot run (no model call available), fall back to the classic
    # builder so the loop never breaks.
    try:
        mc = model_call or DefaultModelCall(root, lane_profile)
        minfo = model_info or _default_model_info(root)
    except Exception as exc:  # noqa: BLE001
        return _classic(None, {"mode": "funnel", "fallback": f"setup_failed: {exc}"})

    budget = CallBudget(limit=max(1, cfg.max_model_calls_per_goal))
    try:
        definition = run_definition_stage(goal, lanes=cfg.lanes, model_call=mc, profile=lane_profile, budget=budget)
        rubric, checks = run_rubric_stage(
            goal,
            definition.text,
            lanes=cfg.lanes,
            survivors=cfg.survivors,
            model_call=mc,
            profile=lane_profile,
            budget=budget,
        )
        product = run_product_stage(
            goal,
            definition.text,
            rubric.text,
            lanes=cfg.lanes,
            survivors=cfg.survivors,
            simplification=cfg.simplification,
            model_call=mc,
            profile=lane_profile,
            budget=budget,
        )
    except Exception as exc:  # noqa: BLE001 - any stage failure falls back to classic
        return _classic(None, {"mode": "funnel", "fallback": f"stage_failed: {exc}", "calls": budget.used})

    enriched_goal = (
        f"{goal}\n\n"
        "An AI design funnel converged the following success definition and implementation plan. "
        "Implement the plan so the success criteria hold; keep the change minimal and verified.\n\n"
        f"## Success definition\n{definition.text}\n\n"
        f"## Implementation plan\n{product.text}\n"
    )

    build_passes = passes if passes is not None else cfg.repair_budget_late
    result = build(
        root,
        goal=enriched_goal,
        profile=profile,
        passes=build_passes,
        promote_on_pass=promote_on_pass,
        timeout_seconds=timeout_seconds,
        refactor_first=refactor_first,
        acceptance_checks=([*(acceptance_checks or []), *checks] or None),
    )
    session = result.get("session")
    if not isinstance(session, dict):
        return result  # builder returned something unexpected; pass it through untouched

    # --- independent cross-family evaluator (advisory, fail-closed-only) ---
    check = _run_external_evaluator(
        original_goal=goal, session=session, cfg=cfg, model_call=mc, model_info=minfo, lane_profile=lane_profile
    )
    if check.get("broke_it") and check.get("independent") and cfg.independent_check_can_self_veto:
        # Self-veto: make promotion HARDER only. The blue gate then rejects/holds.
        session["promotable"] = False
        rejections = list(session.get("session_rejections") or [])
        rejections.append(f"funnel independent evaluator self-veto: {check.get('reason', 'broke it')}")
        session["session_rejections"] = rejections
        check["applied_self_veto"] = True

    session["independent_check"] = check
    session["unaudited_runtime_self_assessment"] = {
        "note": "Internal funnel scores. NOT a verdict — see independent_check for the audited signal.",
        "definition_contradictions": definition.contradictions,
        "definition_convergence": definition.convergence,
        "rubric_survivors": rubric.detail.get("survivors"),
        "product_survivors": product.detail.get("survivors"),
        "simplification_cuts_accepted": product.detail.get("simplification_cuts_accepted", []),
    }
    session["funnel"] = {
        "mode": "funnel",
        "lanes": cfg.lanes,
        "survivors": cfg.survivors,
        "lane_profile": lane_profile,
        "lane_family": family_of(*minfo(lane_profile)) if lane_profile else "",
        "model_calls_used": budget.used,
        "budget_truncated": budget.truncated,
        "acceptance_checks_added": checks,
        "stages": {
            "definition": definition.to_dict(),
            "rubric": rubric.to_dict(),
            "product": product.to_dict(),
        },
    }
    return result
