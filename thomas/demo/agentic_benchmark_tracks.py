from __future__ import annotations

import argparse
from collections.abc import Mapping
from typing import Any


class TrackSpec:
    def __init__(
        self,
        name: str,
        kind: str,
        profile: str,
        mode: str = "auto",
        token_economy: str = "optimal",
        max_iterations: int | None = None,
    ):
        self.name = name
        self.kind = kind
        self.profile = profile
        self.mode = mode
        self.token_economy = token_economy
        self.max_iterations = max_iterations


def _track_capability_class(track: TrackSpec, args: argparse.Namespace) -> str:
    if track.kind == "raw":
        return "text_only"
    if track.kind == "baseline_agent":
        return "tool_using_agent"
    if track.kind == "thomas" and str(args.thomas_runner or "").strip() == "api" and str(track.mode or "") == "swarm":
        return "tool_using_multi_agent"
    return "tool_using_agent"


def _capability_satisfies(actual: str, required: str) -> bool:
    rank = {
        "text_only": 0,
        "tool_using_agent": 1,
        "tool_using_multi_agent": 2,
    }
    return int(rank.get(actual, -1)) >= int(rank.get(required, -1))


def _track_validity_for_task_pack(
    *,
    task_pack: Mapping[str, Any],
    track: TrackSpec,
    args: argparse.Namespace,
) -> tuple[str, str]:
    requirements = dict(task_pack.get("competitor_requirements") or {})
    required_capability = str(requirements.get("required_capability_class") or "").strip()
    if not required_capability:
        return "valid", ""
    actual_capability = _track_capability_class(track, args)
    if _capability_satisfies(actual_capability, required_capability):
        return "valid", ""
    return (
        "invalid_competitor_capability",
        (
            f"track capability `{actual_capability}` does not satisfy required capability "
            f"`{required_capability}` for pack `{task_pack.get('id')}`"
        ),
    )


def _resolve_baseline_runner(task_pack: Mapping[str, Any], args: argparse.Namespace) -> str:
    requested = str(getattr(args, "baseline_runner", "") or "auto").strip().lower() or "auto"
    if requested not in {"auto", "raw", "tool-agent"}:
        raise ValueError(f"Unsupported baseline runner: {requested}")
    if requested != "auto":
        return requested
    requirements = dict(task_pack.get("competitor_requirements") or {})
    required_capability = str(requirements.get("required_capability_class") or "").strip()
    if required_capability and required_capability != "text_only":
        return "tool-agent"
    return "raw"


def _build_baseline_track(task_pack: Mapping[str, Any], args: argparse.Namespace) -> TrackSpec:
    runner = _resolve_baseline_runner(task_pack, args)
    requested_name = str(getattr(args, "baseline_name", "") or "").strip()
    if runner == "raw":
        return TrackSpec(name=requested_name or "baseline_raw", kind="raw", profile=args.profile)
    return TrackSpec(
        name=requested_name or "baseline_agent",
        kind="baseline_agent",
        profile=args.profile,
        mode=str(getattr(args, "baseline_mode", "auto") or "auto"),
        token_economy=str(getattr(args, "baseline_token_economy", "optimal") or "optimal"),
        max_iterations=getattr(args, "baseline_max_iterations", None),
    )


def _resolve_task_timeout_seconds(task: Mapping[str, Any], args: argparse.Namespace) -> float | None:
    pack_budget = float(task.get("time_budget_seconds") or 0.0)
    override_budget = float(getattr(args, "task_timeout_seconds", 0.0) or 0.0)
    positive_budgets = [value for value in (pack_budget, override_budget) if value > 0]
    if not positive_budgets:
        return None
    return float(min(positive_budgets))
