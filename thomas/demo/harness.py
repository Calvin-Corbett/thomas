from __future__ import annotations

import argparse
import json
import random
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.demo.harness_reports import (
    DEFAULT_QUALITY_SCALE,
    DEFAULT_WEIGHTS,
    _write_json,
    aggregate_scorecards,
    build_blind_pack,
    compute_summary,
    load_scorecards,
    write_blind_pack,
    write_run_artifacts,
)

__all__ = [
    "aggregate_scorecards",
    "build_blind_pack",
    "compute_summary",
    "load_scorecards",
    "write_blind_pack",
    "write_run_artifacts",
]

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TASK_PACK = ROOT / "demo" / "task_pack.default.json"
DEFAULT_RUNS_DIR = ROOT / "demo" / "runs"
DEFAULT_COMPETITORS: Sequence[str] = ("thomas", "openclaw")


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
                "validity": str(item.get("validity") or "valid").strip() or "valid",
                "invalid_reason": str(item.get("invalid_reason") or "").strip(),
                "captured_at": str(item.get("captured_at") or "").strip(),
            }
        )
    return normalized


def _print_summary(summary: Mapping[str, Any]) -> None:
    print("")
    print("Metric summary:")
    for competitor, metrics in (summary.get("competitors") or {}).items():
        print(
            f"  {competitor}: validity={metrics.get('validity_rate')}, "
            f"success={metrics.get('success_rate')}, "
            f"avg_time={metrics.get('avg_elapsed_seconds')}s, "
            f"follow_up={metrics.get('avg_follow_up_prompts')}, "
            f"quality={metrics.get('avg_quality_score')}, "
            f"weighted={metrics.get('weighted_score')}"
        )
    ranking = list(summary.get("ranking") or [])
    if ranking:
        print("Secondary ranking:")
        for row in ranking:
            print(f"  #{row.get('rank')} {row.get('competitor')}: {row.get('weighted_score')} / 100")


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
                print(f"  #{row.get('rank')} {row.get('competitor')}: {row.get('weighted_score_mean')} / 100")
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
