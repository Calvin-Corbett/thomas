from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _render_prompts_markdown(task_pack: Mapping[str, Any]) -> str:
    lines: list[str] = [f"# {task_pack.get('name')}", ""]
    description = str(task_pack.get("description") or "").strip()
    if description:
        lines.extend([description, ""])
    protocol = list(task_pack.get("protocol") or [])
    if protocol:
        lines.extend(["## Protocol", ""])
        lines.extend(f"- {item}" for item in protocol)
        lines.append("")
    lines.extend(["## Tasks", ""])
    for idx, task in enumerate(task_pack.get("tasks") or [], start=1):
        lines.append(f"### {idx}. {task.get('title')} (`{task.get('id')}`)")
        budget = task.get("time_budget_seconds")
        if budget:
            lines.append(f"Time budget: {budget} seconds")
        criteria = str(task.get("success_criteria") or "").strip()
        if criteria:
            lines.append(f"Success criteria: {criteria}")
        lines.extend(["", "Prompt:", "", "```text", str(task.get("prompt") or "").strip(), "```", ""])
    return "\n".join(lines).strip() + "\n"


def _render_execution_plan_markdown(
    *,
    task_pack: Mapping[str, Any],
    execution_plan: Sequence[Mapping[str, Any]],
    randomized: bool,
    seed: int | None,
) -> str:
    task_titles = {str(task.get("id") or ""): str(task.get("title") or "") for task in (task_pack.get("tasks") or [])}
    lines = ["# Execution Plan", "", f"- Randomized order: {'yes' if randomized else 'no'}"]
    if randomized:
        lines.append(f"- Seed: {seed if seed is not None else 0}")
    lines.extend(["", "## Steps", ""])
    for row in execution_plan:
        task_id = str(row.get("task_id") or "")
        title = task_titles.get(task_id, task_id)
        lines.append(f"- Step {row.get('step')}: `{row.get('competitor')}` -> `{task_id}` ({title})")
    return "\n".join(lines).strip() + "\n"


def _render_report_markdown(*, run_id: str, task_pack: Mapping[str, Any], summary: Mapping[str, Any]) -> str:
    lines = [
        f"# Head-to-Head Report: {run_id}",
        "",
        f"Task pack: `{task_pack.get('id')}` v{task_pack.get('version')}",
        "",
        "## Execution Validity",
        "",
    ]
    competitors = dict(summary.get("competitors") or {})
    if not competitors:
        lines.append("- No competitor metrics available.")
    else:
        for competitor, metrics in competitors.items():
            eligibility = "eligible" if bool(metrics.get("ranking_eligible")) else "invalid_for_ranking"
            lines.append(
                f"- `{competitor}`: validity_rate={metrics.get('validity_rate')}, "
                f"invalid_tasks={metrics.get('invalid_task_count')}, ranking={eligibility}"
            )
    lines.extend(["", "## Metric Panels", ""])
    for competitor, metrics in competitors.items():
        lines.append(f"### {competitor}")
        for label, key in (
            ("Tasks total", "tasks_total"),
            ("Tasks completed", "tasks_completed"),
            ("Valid task count", "valid_task_count"),
            ("Invalid task count", "invalid_task_count"),
            ("Failure count", "failure_count"),
            ("Validity rate", "validity_rate"),
            ("Success count", "success_count"),
            ("Success rate", "success_rate"),
            ("Artifact success count", "artifact_success_count"),
            ("Artifact success rate", "artifact_success_rate"),
            ("Response confirmation count", "response_confirmed_count"),
            ("Response confirmation rate", "response_confirmed_rate"),
            ("Timeout count", "timeout_count"),
            ("Runaway guard count", "runaway_guard_count"),
            ("Runner error count", "runner_error_count"),
        ):
            lines.append(f"- {label}: {metrics.get(key)}")
        lines.append(f"- Average time: {metrics.get('avg_elapsed_seconds')} seconds")
        lines.append(f"- Average follow-up prompts: {metrics.get('avg_follow_up_prompts')}")
        lines.append(f"- Average quality score: {metrics.get('avg_quality_score')}")
        lines.append(f"- Weighted score base: {metrics.get('weighted_score_base')} / 100")
        lines.append(f"- Weighted score adjusted: {metrics.get('weighted_score')} / 100")
        lines.append(f"- Credibility weighted score: {metrics.get('credibility_weighted_score')} / 100")
        lines.append("")
    if not competitors:
        lines.append("- No metric panels available.")
    for title, key, score_key in (
        ("Ranking (Secondary)", "ranking", "weighted_score"),
        ("Credibility Ranking (Secondary)", "credibility_ranking", "credibility_weighted_score"),
    ):
        lines.extend(["", f"## {title}", ""])
        rows = list(summary.get(key) or [])
        if not rows:
            lines.append("- No ranking data available.")
        else:
            for row in rows:
                lines.append(f"- #{row.get('rank')} `{row.get('competitor')}`: {row.get(score_key)} / 100")
    lines.extend(["", "## Task Winners", ""])
    for row in list(summary.get("task_winners") or []):
        winners = list(row.get("winners") or [])
        lines.append(f"- `{row.get('task_id')}`: {', '.join(winners) if winners else 'no winner'}")
    if not summary.get("task_winners"):
        lines.append("- No task winner data available.")
    return "\n".join(lines).strip() + "\n"


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
    scorecard = {
        "run_id": run_dir.name,
        "created_at": now,
        "task_pack_id": task_pack.get("id"),
        "task_pack_version": task_pack.get("version"),
        "competitors": list(competitors),
        "summary": summary,
    }
    _write_json(run_dir / "scorecard.json", scorecard)
    _write_json(run_dir / "summary.json", scorecard)
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
    overlay_lines = ["competitor,task_id,success,validity,elapsed_seconds,follow_up_prompts,quality_score,evidence,notes"]
    for row in records:
        overlay_lines.append(
            ",".join(
                [
                    str(row.get("competitor") or ""),
                    str(row.get("task_id") or ""),
                    "1" if bool(row.get("success")) else "0",
                    str(row.get("validity") or "valid"),
                    str(row.get("elapsed_seconds") or ""),
                    str(row.get("follow_up_prompts") or ""),
                    str(row.get("quality_score") or ""),
                    str(row.get("evidence") or "").replace(",", ";"),
                    str(row.get("notes") or "").replace(",", ";"),
                ]
            )
        )
    (run_dir / "overlay.csv").write_text("\n".join(overlay_lines) + "\n", encoding="utf-8")
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
                "task_pack_snapshot_sha256": _sha256_file(run_dir / "task_pack.snapshot.json"),
                "execution_plan_sha256": _sha256_file(run_dir / "execution_plan.json"),
                "results_raw_sha256": _sha256_file(run_dir / "results.raw.json"),
                "scorecard_sha256": _sha256_file(run_dir / "scorecard.json"),
            },
        },
    )
    return run_dir
