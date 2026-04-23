from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, MutableMapping, Sequence
from statistics import mean
from typing import Any

DEFAULT_WEIGHTS: dict[str, float] = {
    "success_rate": 0.40,
    "speed": 0.20,
    "follow_up": 0.20,
    "quality": 0.20,
}
DEFAULT_QUALITY_SCALE: dict[str, int] = {"min": 1, "max": 5}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _normalize_lower(values: Mapping[str, float]) -> dict[str, float]:
    if not values:
        return {}
    lo = min(values.values())
    hi = max(values.values())
    if hi == lo:
        return {k: 1.0 for k in values}
    return {k: (hi - v) / (hi - lo) for k, v in values.items()}


def _task_winners(task_id: str, records: Sequence[Mapping[str, Any]]) -> list[str]:
    per_task = [r for r in records if str(r.get("task_id")) == task_id]
    if not per_task:
        return []

    def rank_key(record: Mapping[str, Any]) -> tuple[float, float, float, float]:
        return (
            float(record.get("success", 0)),
            float(record.get("quality_score", 0)),
            -float(record.get("elapsed_seconds", 0)),
            -float(record.get("follow_up_prompts", 0)),
        )

    best = max(rank_key(r) for r in per_task)
    winners = [str(r.get("competitor")) for r in per_task if rank_key(r) == best]
    return sorted(set(winners))


def compute_summary(task_pack: Mapping[str, Any], records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    tasks = list(task_pack.get("tasks") or [])
    task_ids = [str(t.get("id")) for t in tasks]
    weights = dict(task_pack.get("weights") or DEFAULT_WEIGHTS)
    scale = dict(task_pack.get("quality_scale") or DEFAULT_QUALITY_SCALE)
    quality_min = int(scale["min"])
    quality_max = int(scale["max"])
    quality_range = float(quality_max - quality_min)
    task_count = max(1, len(task_ids))

    grouped: MutableMapping[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        competitor = str(record.get("competitor") or "").strip()
        if competitor:
            grouped[competitor].append(record)

    competitors = sorted(grouped.keys())
    competitor_metrics: dict[str, dict[str, Any]] = {}
    speed_basis: dict[str, float] = {}
    follow_basis: dict[str, float] = {}

    for competitor in competitors:
        row = grouped[competitor]
        unique_task_ids = {str(r.get("task_id") or "") for r in row}
        success_count = sum(1 for r in row if bool(r.get("success")))
        invalid_count = sum(1 for r in row if str(r.get("validity") or "valid").strip() != "valid")
        valid_count = max(0, len(row) - invalid_count)
        evidence_count = sum(1 for r in row if str(r.get("evidence") or "").strip())
        artifact_success_count = sum(1 for r in row if bool(r.get("artifact_success")))
        response_confirmed_count = sum(1 for r in row if bool(r.get("response_confirmed")))
        timeout_count = sum(1 for r in row if bool(r.get("timed_out")))
        runaway_guard_count = sum(1 for r in row if bool(r.get("runaway_guarded")))
        runner_error_count = sum(1 for r in row if bool(r.get("runner_error_present")))
        validity_rate = valid_count / float(task_count)
        success_rate = success_count / float(task_count)
        evidence_coverage = evidence_count / float(task_count)
        avg_elapsed = mean(float(r.get("elapsed_seconds") or 0.0) for r in row) if row else 0.0
        avg_follow = mean(float(r.get("follow_up_prompts") or 0) for r in row) if row else 0.0
        avg_quality = mean(float(r.get("quality_score") or quality_min) for r in row) if row else float(quality_min)
        quality_norm = _clamp((avg_quality - quality_min) / quality_range, 0.0, 1.0)

        speed_basis[competitor] = avg_elapsed
        follow_basis[competitor] = avg_follow
        competitor_metrics[competitor] = {
            "tasks_total": len(task_ids),
            "tasks_completed": len(unique_task_ids),
            "missing_task_count": max(0, len(task_ids) - len(unique_task_ids)),
            "valid_task_count": valid_count,
            "invalid_task_count": invalid_count,
            "failure_count": max(0, task_count - success_count - invalid_count),
            "validity_rate": round(validity_rate, 6),
            "success_count": success_count,
            "success_rate": round(success_rate, 6),
            "artifact_success_count": artifact_success_count,
            "artifact_success_rate": round(artifact_success_count / float(task_count), 6),
            "response_confirmed_count": response_confirmed_count,
            "response_confirmed_rate": round(response_confirmed_count / float(task_count), 6),
            "timeout_count": timeout_count,
            "runaway_guard_count": runaway_guard_count,
            "runner_error_count": runner_error_count,
            "evidence_count": evidence_count,
            "evidence_coverage": round(evidence_coverage, 6),
            "avg_elapsed_seconds": round(avg_elapsed, 3),
            "avg_follow_up_prompts": round(avg_follow, 3),
            "avg_quality_score": round(avg_quality, 3),
            "quality_score_norm": round(quality_norm, 6),
        }

    speed_norm = _normalize_lower(speed_basis)
    follow_norm = _normalize_lower(follow_basis)
    weight_total = sum(float(v) for v in weights.values()) or 1.0
    for competitor in competitors:
        metrics = competitor_metrics[competitor]
        base_score = (
            float(weights["success_rate"]) * float(metrics["success_rate"])
            + float(weights["speed"]) * float(speed_norm.get(competitor, 0.0))
            + float(weights["follow_up"]) * float(follow_norm.get(competitor, 0.0))
            + float(weights["quality"]) * float(metrics["quality_score_norm"])
        ) / weight_total
        score = base_score * float(metrics["validity_rate"])
        metrics["speed_norm"] = round(float(speed_norm.get(competitor, 0.0)), 6)
        metrics["follow_up_norm"] = round(float(follow_norm.get(competitor, 0.0)), 6)
        metrics["weighted_score_base"] = round(base_score * 100.0, 3)
        metrics["weighted_score"] = round(score * 100.0, 3)
        metrics["credibility_weighted_score"] = round(
            float(metrics["weighted_score"]) * float(metrics.get("evidence_coverage") or 0.0), 3
        )
        metrics["ranking_eligible"] = bool(metrics["invalid_task_count"] == 0)

    ranking = sorted(
        (
            {"competitor": competitor, "weighted_score": competitor_metrics[competitor]["weighted_score"]}
            for competitor in competitors
        ),
        key=lambda item: item["weighted_score"],
        reverse=True,
    )
    credibility_ranking = sorted(
        (
            {
                "competitor": competitor,
                "credibility_weighted_score": competitor_metrics[competitor]["credibility_weighted_score"],
            }
            for competitor in competitors
        ),
        key=lambda item: item["credibility_weighted_score"],
        reverse=True,
    )
    for idx, row in enumerate(ranking, start=1):
        row["rank"] = idx
    for idx, row in enumerate(credibility_ranking, start=1):
        row["rank"] = idx

    return {
        "weights": weights,
        "quality_scale": scale,
        "competitors": competitor_metrics,
        "ranking": ranking,
        "credibility_ranking": credibility_ranking,
        "task_winners": [{"task_id": task_id, "winners": _task_winners(task_id, records)} for task_id in task_ids],
    }
