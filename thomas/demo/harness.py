from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import defaultdict
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TASK_PACK = ROOT / "demo" / "task_pack.default.json"
DEFAULT_RUNS_DIR = ROOT / "demo" / "runs"
DEFAULT_COMPETITORS: Sequence[str] = ("thomas", "openclaw")
DEFAULT_WEIGHTS: dict[str, float] = {
    "success_rate": 0.40,
    "speed": 0.20,
    "follow_up": 0.20,
    "quality": 0.20,
}
DEFAULT_QUALITY_SCALE: dict[str, int] = {"min": 1, "max": 5}


def _read_json(path: Path) -> Any:
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise ValueError(f"JSON file not found: {path}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def load_task_pack(path: Path) -> dict[str, Any]:
    data = _read_json(path)
    if not isinstance(data, dict):
        raise ValueError("Task pack must be a JSON object.")

    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("Task pack must include a non-empty 'tasks' list.")

    task_ids: set[str] = set()
    normalized_tasks: list[dict[str, Any]] = []
    for idx, task in enumerate(tasks, start=1):
        if not isinstance(task, dict):
            raise ValueError(f"Task #{idx} must be an object.")
        task_id = str(task.get("id") or "").strip()
        title = str(task.get("title") or "").strip()
        prompt = str(task.get("prompt") or "").strip()
        if not task_id:
            raise ValueError(f"Task #{idx} is missing 'id'.")
        if task_id in task_ids:
            raise ValueError(f"Duplicate task id in task pack: {task_id}")
        task_ids.add(task_id)
        if not title:
            raise ValueError(f"Task '{task_id}' is missing 'title'.")
        if not prompt:
            raise ValueError(f"Task '{task_id}' is missing 'prompt'.")
        budget = task.get("time_budget_seconds")
        if budget is not None:
            try:
                budget = int(budget)
            except Exception as exc:
                raise ValueError(f"Task '{task_id}' has non-integer time_budget_seconds.") from exc
            if budget <= 0:
                raise ValueError(f"Task '{task_id}' has invalid time_budget_seconds: {budget}")
        normalized_tasks.append(
            {
                "id": task_id,
                "title": title,
                "prompt": prompt,
                "success_criteria": str(task.get("success_criteria") or "").strip(),
                "time_budget_seconds": budget,
            }
        )

    weights = data.get("weights") or {}
    merged_weights = dict(DEFAULT_WEIGHTS)
    if not isinstance(weights, dict):
        raise ValueError("Task pack 'weights' must be an object.")
    for key in merged_weights:
        if key in weights:
            try:
                merged_weights[key] = float(weights[key])
            except Exception as exc:
                raise ValueError(f"Task pack weight '{key}' must be numeric.") from exc
    if sum(merged_weights.values()) <= 0:
        raise ValueError("Task pack weights must have a positive sum.")

    quality_scale = data.get("quality_scale") or {}
    merged_scale = dict(DEFAULT_QUALITY_SCALE)
    if not isinstance(quality_scale, dict):
        raise ValueError("Task pack 'quality_scale' must be an object.")
    for key in merged_scale:
        if key in quality_scale:
            try:
                merged_scale[key] = int(quality_scale[key])
            except Exception as exc:
                raise ValueError(f"Task pack quality_scale '{key}' must be an integer.") from exc
    if merged_scale["min"] >= merged_scale["max"]:
        raise ValueError("Task pack quality_scale must satisfy min < max.")

    return {
        "id": str(data.get("id") or path.stem),
        "name": str(data.get("name") or "Head-to-Head Demo Task Pack"),
        "version": int(data.get("version") or 1),
        "description": str(data.get("description") or "").strip(),
        "tasks": normalized_tasks,
        "weights": merged_weights,
        "quality_scale": merged_scale,
        "protocol": list(data.get("protocol") or []),
    }


def build_execution_plan(
    *,
    task_pack: Mapping[str, Any],
    competitors: Sequence[str],
    randomize: bool = False,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    tasks = [str(task.get("id") or "").strip() for task in (task_pack.get("tasks") or [])]
    tasks = [task_id for task_id in tasks if task_id]
    competitor_list = [str(c).strip() for c in competitors if str(c).strip()]
    steps: list[dict[str, Any]] = []
    rng = random.Random(seed if seed is not None else 0)

    task_order = list(tasks)
    if randomize:
        rng.shuffle(task_order)

    step_num = 1
    for task_id in task_order:
        run_competitors = list(competitor_list)
        if randomize:
            rng.shuffle(run_competitors)
        for competitor in run_competitors:
            steps.append(
                {
                    "step": step_num,
                    "task_id": task_id,
                    "competitor": competitor,
                }
            )
            step_num += 1
    return steps


def build_results_template(task_pack: Mapping[str, Any], competitors: Sequence[str]) -> list[dict[str, Any]]:
    tasks = list(task_pack.get("tasks") or [])
    scale = dict(task_pack.get("quality_scale") or DEFAULT_QUALITY_SCALE)
    min_quality = int(scale["min"])
    template: list[dict[str, Any]] = []
    for task in tasks:
        task_id = str(task.get("id") or "")
        for competitor in competitors:
            template.append(
                {
                    "task_id": task_id,
                    "competitor": str(competitor),
                    "success": False,
                    "elapsed_seconds": 0.0,
                    "follow_up_prompts": 0,
                    "quality_score": min_quality,
                    "evidence": "",
                    "notes": "",
                    "captured_at": "",
                }
            )
    return template


def validate_records(
    *,
    task_pack: Mapping[str, Any],
    competitors: Sequence[str],
    records: Sequence[Mapping[str, Any]],
    require_evidence: bool = False,
) -> None:
    tasks = list(task_pack.get("tasks") or [])
    task_ids: set[str] = {str(task.get("id") or "").strip() for task in tasks}
    competitor_ids: set[str] = {str(c).strip() for c in competitors if str(c).strip()}
    scale = dict(task_pack.get("quality_scale") or DEFAULT_QUALITY_SCALE)
    min_quality = int(scale["min"])
    max_quality = int(scale["max"])
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()

    if not records:
        errors.append("No result records found.")

    for idx, row in enumerate(records, start=1):
        task_id = str(row.get("task_id") or "").strip()
        competitor = str(row.get("competitor") or "").strip()
        if task_id not in task_ids:
            errors.append(f"Record #{idx}: unknown task_id '{task_id}'.")
        if competitor not in competitor_ids:
            errors.append(f"Record #{idx}: unknown competitor '{competitor}'.")

        key = (task_id, competitor)
        if key in seen:
            errors.append(f"Duplicate record for task '{task_id}' competitor '{competitor}'.")
        seen.add(key)

        elapsed = float(row.get("elapsed_seconds") or 0.0)
        follow_up = int(row.get("follow_up_prompts") or 0)
        quality = int(row.get("quality_score") or 0)
        success = bool(row.get("success"))
        evidence = str(row.get("evidence") or "").strip()
        if elapsed < 0:
            errors.append(f"Record #{idx}: elapsed_seconds must be >= 0.")
        if follow_up < 0:
            errors.append(f"Record #{idx}: follow_up_prompts must be >= 0.")
        if quality < min_quality or quality > max_quality:
            errors.append(f"Record #{idx}: quality_score must be in [{min_quality}, {max_quality}].")
        if require_evidence and success and not evidence:
            errors.append(f"Record #{idx}: evidence is required when success=true.")

    expected: set[tuple[str, str]] = {(task_id, competitor) for task_id in task_ids for competitor in competitor_ids}
    missing = sorted(expected - seen)
    for task_id, competitor in missing:
        errors.append(f"Missing result for task '{task_id}' competitor '{competitor}'.")

    if errors:
        max_errors = 25
        message = "\n".join(f"- {item}" for item in errors[:max_errors])
        remaining = len(errors) - max_errors
        if remaining > 0:
            message += f"\n- ... {remaining} additional errors."
        raise ValueError(f"Invalid results JSON:\n{message}")


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _normalize_higher(values: Mapping[str, float]) -> dict[str, float]:
    if not values:
        return {}
    lo = min(values.values())
    hi = max(values.values())
    if hi == lo:
        return {k: 1.0 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


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
        missing_count = max(0, len(task_ids) - len(unique_task_ids))
        success_count = sum(1 for r in row if bool(r.get("success")))
        evidence_count = sum(1 for r in row if str(r.get("evidence") or "").strip())
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
            "missing_task_count": missing_count,
            "success_count": success_count,
            "success_rate": round(success_rate, 6),
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
        score = (
            float(weights["success_rate"]) * float(metrics["success_rate"])
            + float(weights["speed"]) * float(speed_norm.get(competitor, 0.0))
            + float(weights["follow_up"]) * float(follow_norm.get(competitor, 0.0))
            + float(weights["quality"]) * float(metrics["quality_score_norm"])
        ) / weight_total
        metrics["speed_norm"] = round(float(speed_norm.get(competitor, 0.0)), 6)
        metrics["follow_up_norm"] = round(float(follow_norm.get(competitor, 0.0)), 6)
        metrics["weighted_score"] = round(score * 100.0, 3)
        metrics["credibility_weighted_score"] = round(
            float(metrics["weighted_score"]) * float(metrics.get("evidence_coverage") or 0.0), 3
        )

    ranking = sorted(
        (
            {"competitor": competitor, "weighted_score": competitor_metrics[competitor]["weighted_score"]}
            for competitor in competitors
        ),
        key=lambda item: item["weighted_score"],
        reverse=True,
    )
    for idx, row in enumerate(ranking, start=1):
        row["rank"] = idx

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
    for idx, row in enumerate(credibility_ranking, start=1):
        row["rank"] = idx

    task_winners = [{"task_id": task_id, "winners": _task_winners(task_id, records)} for task_id in task_ids]
    return {
        "weights": weights,
        "quality_scale": scale,
        "competitors": competitor_metrics,
        "ranking": ranking,
        "credibility_ranking": credibility_ranking,
        "task_winners": task_winners,
    }


def _render_prompts_markdown(task_pack: Mapping[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# {task_pack.get('name')}")
    lines.append("")
    description = str(task_pack.get("description") or "").strip()
    if description:
        lines.append(description)
        lines.append("")
    protocol = list(task_pack.get("protocol") or [])
    if protocol:
        lines.append("## Protocol")
        lines.append("")
        for item in protocol:
            lines.append(f"- {item}")
        lines.append("")
    lines.append("## Tasks")
    lines.append("")
    for idx, task in enumerate(task_pack.get("tasks") or [], start=1):
        lines.append(f"### {idx}. {task.get('title')} (`{task.get('id')}`)")
        budget = task.get("time_budget_seconds")
        if budget:
            lines.append(f"Time budget: {budget} seconds")
        criteria = str(task.get("success_criteria") or "").strip()
        if criteria:
            lines.append(f"Success criteria: {criteria}")
        lines.append("")
        lines.append("Prompt:")
        lines.append("")
        lines.append("```text")
        lines.append(str(task.get("prompt") or "").strip())
        lines.append("```")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _render_report_markdown(
    *,
    run_id: str,
    task_pack: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> str:
    lines: list[str] = []
    lines.append(f"# Head-to-Head Report: {run_id}")
    lines.append("")
    lines.append(f"Task pack: `{task_pack.get('id')}` v{task_pack.get('version')}")
    lines.append("")

    ranking = list(summary.get("ranking") or [])
    lines.append("## Ranking")
    lines.append("")
    if not ranking:
        lines.append("- No ranking data available.")
    else:
        for row in ranking:
            lines.append(f"- #{row.get('rank')} `{row.get('competitor')}`: " f"{row.get('weighted_score')} / 100")
    lines.append("")

    credibility = list(summary.get("credibility_ranking") or [])
    lines.append("## Credibility Ranking (Evidence-adjusted)")
    lines.append("")
    if not credibility:
        lines.append("- No credibility ranking data available.")
    else:
        for row in credibility:
            lines.append(
                f"- #{row.get('rank')} `{row.get('competitor')}`: " f"{row.get('credibility_weighted_score')} / 100"
            )
    lines.append("")

    lines.append("## Per Competitor Metrics")
    lines.append("")
    competitors = dict(summary.get("competitors") or {})
    if not competitors:
        lines.append("- No competitor metrics available.")
    else:
        for competitor, metrics in competitors.items():
            lines.append(f"### {competitor}")
            lines.append(f"- Success rate: {metrics.get('success_rate')}")
            lines.append(
                f"- Evidence coverage: {metrics.get('evidence_coverage')} "
                f"({metrics.get('evidence_count')}/{metrics.get('tasks_total')})"
            )
            lines.append(f"- Average time: {metrics.get('avg_elapsed_seconds')} seconds")
            lines.append(f"- Average follow-up prompts: {metrics.get('avg_follow_up_prompts')}")
            lines.append(f"- Average quality score: {metrics.get('avg_quality_score')}")
            lines.append(f"- Weighted score: {metrics.get('weighted_score')} / 100")
            lines.append(f"- Credibility weighted score: {metrics.get('credibility_weighted_score')} / 100")
            lines.append("")

    lines.append("## Task Winners")
    lines.append("")
    task_winners = list(summary.get("task_winners") or [])
    if not task_winners:
        lines.append("- No task winner data available.")
    else:
        for row in task_winners:
            task_id = str(row.get("task_id") or "")
            winners = list(row.get("winners") or [])
            if winners:
                lines.append(f"- `{task_id}`: {', '.join(winners)}")
            else:
                lines.append(f"- `{task_id}`: no winner")
    lines.append("")

    return "\n".join(lines).strip() + "\n"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _render_execution_plan_markdown(
    *,
    task_pack: Mapping[str, Any],
    execution_plan: Sequence[Mapping[str, Any]],
    randomized: bool,
    seed: int | None,
) -> str:
    task_titles = {str(task.get("id") or ""): str(task.get("title") or "") for task in (task_pack.get("tasks") or [])}
    lines: list[str] = []
    lines.append("# Execution Plan")
    lines.append("")
    lines.append(f"- Randomized order: {'yes' if randomized else 'no'}")
    if randomized:
        lines.append(f"- Seed: {seed if seed is not None else 0}")
    lines.append("")
    lines.append("## Steps")
    lines.append("")
    for row in execution_plan:
        task_id = str(row.get("task_id") or "")
        title = task_titles.get(task_id, task_id)
        lines.append(f"- Step {row.get('step')}: `{row.get('competitor')}` -> `{task_id}` ({title})")
    lines.append("")
    return "\n".join(lines).strip() + "\n"


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
        competitors = dict(summary.get("competitors") or {})
        for competitor, metrics in competitors.items():
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
    for idx, row in enumerate(ranking, start=1):
        row["rank"] = idx

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
    for idx, row in enumerate(credibility_ranking, start=1):
        row["rank"] = idx

    return {
        "runs_count": len(scorecards),
        "competitors": competitors,
        "ranking": ranking,
        "credibility_ranking": credibility_ranking,
    }


def build_blind_pack(
    records: Sequence[Mapping[str, Any]],
    *,
    seed: int = 0,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    rows = list(records)
    rng = random.Random(int(seed))
    rng.shuffle(rows)
    samples: list[dict[str, Any]] = []
    answer_key: dict[str, dict[str, str]] = {}
    for idx, row in enumerate(rows, start=1):
        sample_id = f"S{idx:03d}"
        task_id = str(row.get("task_id") or "")
        competitor = str(row.get("competitor") or "")
        sample = {
            "sample_id": sample_id,
            "task_id": task_id,
            "elapsed_seconds": float(row.get("elapsed_seconds") or 0.0),
            "follow_up_prompts": int(row.get("follow_up_prompts") or 0),
            "evidence": str(row.get("evidence") or ""),
            "notes": str(row.get("notes") or ""),
            "judge_quality_score": "",
            "judge_success_override": "",
            "judge_comments": "",
        }
        samples.append(sample)
        answer_key[sample_id] = {
            "task_id": task_id,
            "competitor": competitor,
        }
    return samples, answer_key


def write_blind_pack(
    *,
    run_dir: Path,
    records: Sequence[Mapping[str, Any]],
    seed: int = 0,
    out_dir: Path | None = None,
) -> Path:
    target = out_dir if out_dir is not None else (run_dir / "blind_pack")
    target.mkdir(parents=True, exist_ok=True)
    samples, answer_key = build_blind_pack(records, seed=seed)
    _write_json(target / "blind_pack.json", {"seed": int(seed), "samples": samples})
    _write_json(target / "blind_answer_key.json", {"seed": int(seed), "answers": answer_key})

    sheet_path = target / "blind_judging_sheet.csv"
    with sheet_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "sample_id",
                "task_id",
                "elapsed_seconds",
                "follow_up_prompts",
                "evidence",
                "notes",
                "judge_quality_score",
                "judge_success_override",
                "judge_comments",
            ],
        )
        writer.writeheader()
        for row in samples:
            writer.writerow(row)
    return target


def write_run_artifacts(
    *,
    runs_dir: Path,
    run_id: str,
    task_pack: Mapping[str, Any],
    competitors: Sequence[str],
    execution_plan: Sequence[Mapping[str, Any]],
    randomized_order: bool,
    random_seed: int | None,
    require_evidence: bool,
    records: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_dir = runs_dir / run_id
    suffix = 1
    while run_dir.exists():
        run_dir = runs_dir / f"{run_id}-{suffix}"
        suffix += 1
    run_dir.mkdir(parents=True, exist_ok=False)

    now = datetime.now(timezone.utc).isoformat()
    _write_json(run_dir / "task_pack.snapshot.json", task_pack)
    _write_json(run_dir / "results.raw.json", list(records))
    _write_json(run_dir / "execution_plan.json", list(execution_plan))
    _write_json(
        run_dir / "scorecard.json",
        {
            "run_id": run_dir.name,
            "created_at": now,
            "task_pack_id": task_pack.get("id"),
            "task_pack_version": task_pack.get("version"),
            "competitors": list(competitors),
            "summary": summary,
        },
    )
    (run_dir / "task_prompts.md").write_text(_render_prompts_markdown(task_pack), encoding="utf-8")
    (run_dir / "execution_plan.md").write_text(
        _render_execution_plan_markdown(
            task_pack=task_pack,
            execution_plan=execution_plan,
            randomized=randomized_order,
            seed=random_seed,
        ),
        encoding="utf-8",
    )
    (run_dir / "report.md").write_text(
        _render_report_markdown(run_id=run_dir.name, task_pack=task_pack, summary=summary),
        encoding="utf-8",
    )

    overlay_lines = [
        "competitor,task_id,success,elapsed_seconds,follow_up_prompts,quality_score,evidence,notes",
    ]
    for row in records:
        overlay_lines.append(
            ",".join(
                [
                    str(row.get("competitor") or ""),
                    str(row.get("task_id") or ""),
                    "1" if bool(row.get("success")) else "0",
                    str(row.get("elapsed_seconds") or ""),
                    str(row.get("follow_up_prompts") or ""),
                    str(row.get("quality_score") or ""),
                    str(row.get("evidence") or "").replace(",", ";"),
                    str(row.get("notes") or "").replace(",", ";"),
                ]
            )
        )
    (run_dir / "overlay.csv").write_text("\n".join(overlay_lines) + "\n", encoding="utf-8")

    scorecard_path = run_dir / "scorecard.json"
    results_path = run_dir / "results.raw.json"
    task_pack_path = run_dir / "task_pack.snapshot.json"
    execution_plan_path = run_dir / "execution_plan.json"
    _write_json(
        run_dir / "manifest.json",
        {
            "run_id": run_dir.name,
            "created_at": now,
            "randomized_order": bool(randomized_order),
            "random_seed": random_seed if randomized_order else None,
            "require_evidence": bool(require_evidence),
            "competitors": list(competitors),
            "hashes": {
                "task_pack_snapshot_sha256": _sha256_file(task_pack_path),
                "execution_plan_sha256": _sha256_file(execution_plan_path),
                "results_raw_sha256": _sha256_file(results_path),
                "scorecard_sha256": _sha256_file(scorecard_path),
            },
        },
    )
    return run_dir


def _ask(
    *,
    label: str,
    parse_fn: Callable[[str], Any],
    validate_fn: Callable[[Any], bool],
    error: str,
    input_fn: Callable[[str], str],
) -> Any:
    while True:
        raw = str(input_fn(label)).strip()
        try:
            value = parse_fn(raw)
        except (ValueError, TypeError):
            value = None
        if value is not None and validate_fn(value):
            return value
        print(error)


def _ask_optional(label: str, input_fn: Callable[[str], str]) -> str:
    return str(input_fn(label)).strip()


def collect_records_interactive(
    *,
    task_pack: Mapping[str, Any],
    competitors: Sequence[str],
    execution_plan: Sequence[Mapping[str, Any]],
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    tasks = list(task_pack.get("tasks") or [])
    task_map = {str(task.get("id") or ""): task for task in tasks}
    min_quality = int((task_pack.get("quality_scale") or DEFAULT_QUALITY_SCALE)["min"])
    max_quality = int((task_pack.get("quality_scale") or DEFAULT_QUALITY_SCALE)["max"])
    records: list[dict[str, Any]] = []

    output_fn("")
    output_fn("Paste each prompt into each assistant, then enter observed metrics.")
    output_fn("Use elapsed seconds from first send until complete final answer.")
    output_fn("")

    current_task_id = ""
    total_steps = len(execution_plan)
    for row in execution_plan:
        step = int(row.get("step") or 0)
        task_id = str(row.get("task_id") or "")
        competitor = str(row.get("competitor") or "")
        task = task_map.get(task_id) or {}
        if task_id != current_task_id:
            current_task_id = task_id
            output_fn(f"[Task] {task.get('title')} ({task_id})")
            budget = task.get("time_budget_seconds")
            if budget:
                output_fn(f"Time budget: {budget} seconds")
            criteria = str(task.get("success_criteria") or "").strip()
            if criteria:
                output_fn(f"Success criteria: {criteria}")
            output_fn("Prompt:")
            output_fn(str(task.get("prompt") or "").strip())
            output_fn("")

        output_fn(f"[Step {step}/{total_steps}] Result for {competitor}")
        budget = task.get("time_budget_seconds")
        if budget:
            output_fn(f"Budget reminder: {budget} seconds")
        success = _ask(
            label="success (y/n): ",
            parse_fn=lambda s: s.lower(),
            validate_fn=lambda s: s in {"y", "yes", "n", "no"},
            error="Enter y or n.",
            input_fn=input_fn,
        )
        elapsed = _ask(
            label="elapsed seconds: ",
            parse_fn=float,
            validate_fn=lambda x: x >= 0.0,
            error="Enter a number >= 0.",
            input_fn=input_fn,
        )
        follow_up = _ask(
            label="follow-up prompts needed: ",
            parse_fn=int,
            validate_fn=lambda x: x >= 0,
            error="Enter an integer >= 0.",
            input_fn=input_fn,
        )
        quality = _ask(
            label=f"quality score ({min_quality}-{max_quality}): ",
            parse_fn=int,
            validate_fn=lambda x: min_quality <= x <= max_quality,
            error=f"Enter an integer between {min_quality} and {max_quality}.",
            input_fn=input_fn,
        )
        evidence = _ask_optional("evidence path/url (optional): ", input_fn)
        notes = _ask_optional("notes (optional): ", input_fn)
        records.append(
            {
                "task_id": task_id,
                "competitor": competitor,
                "success": success in {"y", "yes"},
                "elapsed_seconds": round(float(elapsed), 3),
                "follow_up_prompts": int(follow_up),
                "quality_score": int(quality),
                "evidence": evidence,
                "notes": notes,
                "captured_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        output_fn("")
    return records


def load_records_json(path: Path) -> list[dict[str, Any]]:
    data = _read_json(path)
    if not isinstance(data, list):
        raise ValueError("results JSON must be a list of records.")
    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Record #{idx} must be an object.")
        normalized.append(
            {
                "task_id": str(item.get("task_id") or "").strip(),
                "competitor": str(item.get("competitor") or "").strip(),
                "success": bool(item.get("success")),
                "elapsed_seconds": float(item.get("elapsed_seconds") or 0.0),
                "follow_up_prompts": int(item.get("follow_up_prompts") or 0),
                "quality_score": int(item.get("quality_score") or 0),
                "evidence": str(item.get("evidence") or "").strip(),
                "notes": str(item.get("notes") or "").strip(),
                "captured_at": str(item.get("captured_at") or "").strip(),
            }
        )
    return normalized


def _print_summary(summary: Mapping[str, Any]) -> None:
    print("")
    print("Score summary:")
    ranking = list(summary.get("ranking") or [])
    for row in ranking:
        print(f"  #{row.get('rank')} {row.get('competitor')}: {row.get('weighted_score')} / 100")
    credibility = list(summary.get("credibility_ranking") or [])
    if credibility:
        print("")
        print("Credibility ranking (evidence-adjusted):")
        for row in credibility:
            print(f"  #{row.get('rank')} {row.get('competitor')}: " f"{row.get('credibility_weighted_score')} / 100")
    print("")
    for competitor, metrics in (summary.get("competitors") or {}).items():
        print(
            f"  {competitor}: success={metrics.get('success_rate')}, "
            f"evidence={metrics.get('evidence_coverage')}, "
            f"avg_time={metrics.get('avg_elapsed_seconds')}s, "
            f"follow_up={metrics.get('avg_follow_up_prompts')}, "
            f"quality={metrics.get('avg_quality_score')}"
        )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a reproducible head-to-head assistant demo.")
    parser.add_argument("--task-pack", default=str(DEFAULT_TASK_PACK), help="Path to task pack JSON file.")
    parser.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR), help="Directory for run artifacts.")
    parser.add_argument("--run-id", default="", help="Optional run id; default is UTC timestamp.")
    parser.add_argument(
        "--competitor",
        action="append",
        default=[],
        help="Competitor label (repeatable). Defaults to: thomas, openclaw.",
    )
    parser.add_argument(
        "--results-json",
        default="",
        help="Optional pre-recorded results JSON list. If provided, interactive prompts are skipped.",
    )
    parser.add_argument(
        "--template-out",
        default="",
        help="Optional path to write a prefilled results template JSON.",
    )
    parser.add_argument(
        "--template-only",
        action="store_true",
        help="Write results template JSON and exit (requires --template-out).",
    )
    parser.add_argument(
        "--randomize-order",
        action="store_true",
        help="Randomize task/competitor execution order (deterministic with --seed).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Seed used with --randomize-order.",
    )
    parser.add_argument(
        "--require-evidence",
        action="store_true",
        help="Require non-empty evidence when success=true.",
    )
    parser.add_argument(
        "--aggregate-from",
        default="",
        help="Directory containing run folders with scorecard.json to aggregate.",
    )
    parser.add_argument(
        "--aggregate-out",
        default="",
        help="Optional path for aggregate JSON output. Default: <aggregate-from>/aggregate.scorecard.json",
    )
    parser.add_argument(
        "--blind-pack-from",
        default="",
        help="Run directory containing results.raw.json to generate blind judging files.",
    )
    parser.add_argument(
        "--blind-seed",
        type=int,
        default=0,
        help="Shuffle seed for blind judging pack generation.",
    )
    parser.add_argument(
        "--blind-out",
        default="",
        help="Optional output directory for blind pack. Default: <run_dir>/blind_pack",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    if args.blind_pack_from:
        run_dir = Path(args.blind_pack_from).resolve()
        results_path = run_dir / "results.raw.json"
        records = load_records_json(results_path)
        blind_out = Path(args.blind_out).resolve() if str(args.blind_out or "").strip() else None
        pack_dir = write_blind_pack(
            run_dir=run_dir,
            records=records,
            seed=int(args.blind_seed),
            out_dir=blind_out,
        )
        print(f"Blind judging pack written to: {pack_dir}")
        print(f"  - {pack_dir / 'blind_pack.json'}")
        print(f"  - {pack_dir / 'blind_answer_key.json'}")
        print(f"  - {pack_dir / 'blind_judging_sheet.csv'}")
        return 0

    if args.aggregate_from:
        aggregate_dir = Path(args.aggregate_from).resolve()
        scorecards = load_scorecards(aggregate_dir)
        aggregate = aggregate_scorecards(scorecards)
        out_path = (
            Path(args.aggregate_out).resolve()
            if str(args.aggregate_out or "").strip()
            else aggregate_dir / "aggregate.scorecard.json"
        )
        _write_json(
            out_path,
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source_runs_dir": str(aggregate_dir),
                "summary": aggregate,
            },
        )
        print(f"Aggregate written to: {out_path}")
        ranking = list(aggregate.get("ranking") or [])
        if ranking:
            print("Aggregate ranking:")
            for row in ranking:
                print(f"  #{row.get('rank')} {row.get('competitor')}: " f"{row.get('weighted_score_mean')} / 100")
        return 0

    task_pack = load_task_pack(Path(args.task_pack).resolve())
    competitors = tuple(dict.fromkeys([str(c).strip() for c in (args.competitor or []) if str(c).strip()]))
    if not competitors:
        competitors = tuple(DEFAULT_COMPETITORS)

    run_id = str(args.run_id).strip() or datetime.now(timezone.utc).strftime("run-%Y%m%d-%H%M%S")
    runs_dir = Path(args.runs_dir).resolve()
    random_seed: int | None = int(args.seed) if args.randomize_order else None
    execution_plan = build_execution_plan(
        task_pack=task_pack,
        competitors=competitors,
        randomize=bool(args.randomize_order),
        seed=random_seed,
    )
    template_records = build_results_template(task_pack, competitors)

    if args.template_only and not args.template_out:
        raise ValueError("--template-only requires --template-out <path>.")
    if args.template_out:
        template_path = Path(args.template_out).resolve()
        template_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(template_path, template_records)
        print(f"Results template written to: {template_path}")
        if args.template_only:
            return 0

    if args.results_json:
        records = load_records_json(Path(args.results_json).resolve())
    else:
        records = collect_records_interactive(
            task_pack=task_pack,
            competitors=competitors,
            execution_plan=execution_plan,
        )

    validate_records(
        task_pack=task_pack,
        competitors=competitors,
        records=records,
        require_evidence=bool(args.require_evidence),
    )
    summary = compute_summary(task_pack, records)
    run_dir = write_run_artifacts(
        runs_dir=runs_dir,
        run_id=run_id,
        task_pack=task_pack,
        competitors=competitors,
        execution_plan=execution_plan,
        randomized_order=bool(args.randomize_order),
        random_seed=random_seed,
        require_evidence=bool(args.require_evidence),
        records=records,
        summary=summary,
    )
    _print_summary(summary)
    print("")
    print(f"Artifacts written to: {run_dir}")
    print(f"  - {run_dir / 'scorecard.json'}")
    print(f"  - {run_dir / 'manifest.json'}")
    print(f"  - {run_dir / 'execution_plan.json'}")
    print(f"  - {run_dir / 'execution_plan.md'}")
    print(f"  - {run_dir / 'results.raw.json'}")
    print(f"  - {run_dir / 'task_prompts.md'}")
    print(f"  - {run_dir / 'report.md'}")
    print(f"  - {run_dir / 'overlay.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
