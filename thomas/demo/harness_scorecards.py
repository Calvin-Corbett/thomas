from __future__ import annotations

import json
from collections.abc import Mapping, MutableMapping, Sequence
from pathlib import Path
from statistics import mean
from typing import Any


def _read_json(path: Path) -> Any:
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise ValueError(f"JSON file not found: {path}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def load_scorecards(runs_dir: Path) -> list[dict[str, Any]]:
    if not runs_dir.exists():
        raise ValueError(f"Runs directory not found: {runs_dir}")
    scorecards: list[dict[str, Any]] = []
    for child in sorted(runs_dir.iterdir()):
        if not child.is_dir():
            continue
        scorecard_path = child / "scorecard.json"
        if not scorecard_path.exists():
            continue
        data = _read_json(scorecard_path)
        if isinstance(data, dict):
            scorecards.append(data)
    if not scorecards:
        raise ValueError(f"No scorecard.json files found under: {runs_dir}")
    return scorecards


def aggregate_scorecards(scorecards: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not scorecards:
        raise ValueError("No scorecards provided for aggregation.")
    bucket: MutableMapping[str, dict[str, Any]] = {}
    for card in scorecards:
        run_id = str(card.get("run_id") or "")
        summary = dict(card.get("summary") or {})
        for competitor, metrics in dict(summary.get("competitors") or {}).items():
            row = bucket.setdefault(
                str(competitor),
                {
                    "runs": 0,
                    "weighted_scores": [],
                    "credibility_weighted_scores": [],
                    "success_rates": [],
                    "avg_elapsed_seconds": [],
                    "avg_follow_up_prompts": [],
                    "avg_quality_scores": [],
                    "evidence_coverage": [],
                    "run_ids": [],
                },
            )
            row["runs"] += 1
            row["run_ids"].append(run_id)
            row["weighted_scores"].append(float(metrics.get("weighted_score") or 0.0))
            row["credibility_weighted_scores"].append(float(metrics.get("credibility_weighted_score") or 0.0))
            row["success_rates"].append(float(metrics.get("success_rate") or 0.0))
            row["avg_elapsed_seconds"].append(float(metrics.get("avg_elapsed_seconds") or 0.0))
            row["avg_follow_up_prompts"].append(float(metrics.get("avg_follow_up_prompts") or 0.0))
            row["avg_quality_scores"].append(float(metrics.get("avg_quality_score") or 0.0))
            row["evidence_coverage"].append(float(metrics.get("evidence_coverage") or 0.0))

    competitors: dict[str, dict[str, Any]] = {}
    for competitor, stats in bucket.items():
        competitors[competitor] = {
            "runs": stats["runs"],
            "weighted_score_mean": round(mean(stats["weighted_scores"]), 3),
            "credibility_weighted_score_mean": round(mean(stats["credibility_weighted_scores"]), 3),
            "success_rate_mean": round(mean(stats["success_rates"]), 6),
            "avg_elapsed_seconds_mean": round(mean(stats["avg_elapsed_seconds"]), 3),
            "avg_follow_up_prompts_mean": round(mean(stats["avg_follow_up_prompts"]), 3),
            "avg_quality_score_mean": round(mean(stats["avg_quality_scores"]), 3),
            "evidence_coverage_mean": round(mean(stats["evidence_coverage"]), 6),
            "run_ids": sorted(stats["run_ids"]),
        }

    ranking = sorted(
        (
            {"competitor": competitor, "weighted_score_mean": row["weighted_score_mean"]}
            for competitor, row in competitors.items()
        ),
        key=lambda item: float(item["weighted_score_mean"]),
        reverse=True,
    )
    credibility_ranking = sorted(
        (
            {
                "competitor": competitor,
                "credibility_weighted_score_mean": row["credibility_weighted_score_mean"],
            }
            for competitor, row in competitors.items()
        ),
        key=lambda item: float(item["credibility_weighted_score_mean"]),
        reverse=True,
    )
    for idx, row in enumerate(ranking, start=1):
        row["rank"] = idx
    for idx, row in enumerate(credibility_ranking, start=1):
        row["rank"] = idx

    return {
        "runs_count": len(scorecards),
        "competitors": competitors,
        "ranking": ranking,
        "credibility_ranking": credibility_ranking,
    }
