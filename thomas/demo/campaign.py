from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from collections.abc import Mapping, Sequence

from thomas.demo.browser_duel import (
    DEFAULT_RUNS_DIR as DEFAULT_BROWSER_RUNS_DIR,
)
from thomas.demo.browser_duel import (
    build_results_from_browser,
    load_adapters,
    parse_target_args,
    run_dual_browser_demo,
)
from thomas.demo.harness import (
    aggregate_scorecards,
    build_execution_plan,
    compute_summary,
    load_task_pack,
    validate_records,
    write_blind_pack,
    write_run_artifacts,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TASK_PACK = ROOT / "demo" / "task_pack.default.json"
DEFAULT_CAMPAIGNS_DIR = ROOT / "demo" / "campaigns"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def build_run_index_rows(scorecards: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for card in scorecards:
        run_id = str(card.get("run_id") or "")
        summary = dict(card.get("summary") or {})
        competitors = dict(summary.get("competitors") or {})
        for competitor, metrics in competitors.items():
            rows.append(
                {
                    "run_id": run_id,
                    "competitor": str(competitor),
                    "weighted_score": float(metrics.get("weighted_score") or 0.0),
                    "credibility_weighted_score": float(metrics.get("credibility_weighted_score") or 0.0),
                    "success_rate": float(metrics.get("success_rate") or 0.0),
                    "avg_elapsed_seconds": float(metrics.get("avg_elapsed_seconds") or 0.0),
                    "avg_follow_up_prompts": float(metrics.get("avg_follow_up_prompts") or 0.0),
                    "avg_quality_score": float(metrics.get("avg_quality_score") or 0.0),
                    "evidence_coverage": float(metrics.get("evidence_coverage") or 0.0),
                }
            )
    rows.sort(key=lambda row: (str(row["run_id"]), str(row["competitor"])))
    return rows


def render_campaign_report(
    *,
    campaign_id: str,
    aggregate: Mapping[str, Any],
    runs_attempted: int,
    runs_completed: int,
) -> str:
    lines: list[str] = []
    lines.append(f"# Demo Campaign Report: {campaign_id}")
    lines.append("")
    lines.append(f"- Runs attempted: {runs_attempted}")
    lines.append(f"- Runs completed: {runs_completed}")
    lines.append(f"- Runs aggregated: {aggregate.get('runs_count')}")
    lines.append("")

    lines.append("## Aggregate Ranking")
    lines.append("")
    ranking = list(aggregate.get("ranking") or [])
    if not ranking:
        lines.append("- No ranking data available.")
    else:
        for row in ranking:
            lines.append(
                f"- #{row.get('rank')} `{row.get('competitor')}`: "
                f"{row.get('weighted_score_mean')} / 100"
            )
    lines.append("")

    lines.append("## Aggregate Credibility Ranking")
    lines.append("")
    cred = list(aggregate.get("credibility_ranking") or [])
    if not cred:
        lines.append("- No credibility ranking data available.")
    else:
        for row in cred:
            lines.append(
                f"- #{row.get('rank')} `{row.get('competitor')}`: "
                f"{row.get('credibility_weighted_score_mean')} / 100"
            )
    lines.append("")

    lines.append("## Per Competitor Means")
    lines.append("")
    competitors = dict(aggregate.get("competitors") or {})
    if not competitors:
        lines.append("- No competitor metrics.")
    else:
        for competitor, metrics in competitors.items():
            lines.append(f"### {competitor}")
            lines.append(f"- runs: {metrics.get('runs')}")
            lines.append(f"- weighted score mean: {metrics.get('weighted_score_mean')}")
            lines.append(
                f"- credibility weighted score mean: {metrics.get('credibility_weighted_score_mean')}"
            )
            lines.append(f"- success rate mean: {metrics.get('success_rate_mean')}")
            lines.append(f"- avg elapsed seconds mean: {metrics.get('avg_elapsed_seconds_mean')}")
            lines.append(f"- avg follow-up prompts mean: {metrics.get('avg_follow_up_prompts_mean')}")
            lines.append(f"- avg quality score mean: {metrics.get('avg_quality_score_mean')}")
            lines.append(f"- evidence coverage mean: {metrics.get('evidence_coverage_mean')}")
            lines.append("")

    return "\n".join(lines).strip() + "\n"


def run_campaign(
    *,
    campaign_id: str,
    runs_count: int,
    task_pack_path: Path,
    target_pairs: Sequence[str],
    selectors_json: Path | None,
    cdp_url: str,
    browser: str,
    launch_browser: bool,
    type_delay_ms: int,
    reply_timeout: float,
    randomize_order: bool,
    base_seed: int,
    runtime_root: Path | None,
    campaigns_dir: Path,
    require_evidence: bool,
    generate_blind_packs: bool,
    continue_on_error: bool,
) -> Path:
    if runs_count <= 0:
        raise ValueError("runs_count must be >= 1.")

    task_pack = load_task_pack(task_pack_path.resolve())
    targets = parse_target_args(target_pairs)
    competitors = tuple(targets.keys())
    adapters = load_adapters(selectors_json.resolve() if selectors_json else None, competitors)
    quality_min = int((task_pack.get("quality_scale") or {"min": 1}).get("min") or 1)

    campaign_dir = campaigns_dir.resolve() / campaign_id
    campaign_dir.mkdir(parents=True, exist_ok=False)
    browser_runs_dir = campaign_dir / "browser_runs"
    scored_runs_dir = campaign_dir / "scored_runs"
    publish_dir = campaign_dir / "publish"
    browser_runs_dir.mkdir(parents=True, exist_ok=True)
    scored_runs_dir.mkdir(parents=True, exist_ok=True)
    publish_dir.mkdir(parents=True, exist_ok=True)

    _write_json(campaign_dir / "targets.json", targets)
    _write_json(campaign_dir / "task_pack.snapshot.json", task_pack)
    _write_json(
        campaign_dir / "campaign_config.json",
        {
            "campaign_id": campaign_id,
            "runs_count": runs_count,
            "cdp_url": cdp_url,
            "browser": browser,
            "launch_browser": bool(launch_browser),
            "type_delay_ms": int(type_delay_ms),
            "reply_timeout": float(reply_timeout),
            "randomize_order": bool(randomize_order),
            "base_seed": int(base_seed),
            "require_evidence": bool(require_evidence),
            "generate_blind_packs": bool(generate_blind_packs),
            "continue_on_error": bool(continue_on_error),
        },
    )

    run_status: list[dict[str, Any]] = []
    scorecards: list[dict[str, Any]] = []

    for i in range(runs_count):
        run_index = i + 1
        run_id = f"{campaign_id}-r{run_index:02d}"
        run_seed = int(base_seed) + i
        execution_plan = build_execution_plan(
            task_pack=task_pack,
            competitors=competitors,
            randomize=bool(randomize_order),
            seed=run_seed,
        )
        browser_run_dir = browser_runs_dir / run_id
        started_at = datetime.now(timezone.utc).isoformat()

        try:
            browser_results = run_dual_browser_demo(
                task_pack=task_pack,
                execution_plan=execution_plan,
                targets=targets,
                adapters=adapters,
                cdp_url=cdp_url,
                launch_browser=bool(launch_browser),
                browser=browser,
                type_delay_ms=int(type_delay_ms),
                reply_timeout_s=float(reply_timeout),
                runtime_root=runtime_root or (ROOT / "runtime"),
                run_dir=browser_run_dir,
            )
            _write_json(browser_run_dir / "browser_results.raw.json", browser_results)
            records = build_results_from_browser(
                browser_results=browser_results,
                quality_min=quality_min,
            )
            _write_json(browser_run_dir / "results.template.from_browser.json", records)

            validate_records(
                task_pack=task_pack,
                competitors=competitors,
                records=records,
                require_evidence=bool(require_evidence),
            )
            summary = compute_summary(task_pack, records)
            scored_run_dir = write_run_artifacts(
                runs_dir=scored_runs_dir,
                run_id=run_id,
                task_pack=task_pack,
                competitors=competitors,
                execution_plan=execution_plan,
                randomized_order=bool(randomize_order),
                random_seed=run_seed if randomize_order else None,
                require_evidence=bool(require_evidence),
                records=records,
                summary=summary,
            )
            if generate_blind_packs:
                write_blind_pack(
                    run_dir=scored_run_dir,
                    records=records,
                    seed=run_seed,
                )

            card = _read_json(scored_run_dir / "scorecard.json")
            if isinstance(card, dict):
                scorecards.append(card)

            run_status.append(
                {
                    "run_id": run_id,
                    "run_seed": run_seed,
                    "status": "ok",
                    "started_at": started_at,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "browser_run_dir": str(browser_run_dir),
                    "scored_run_dir": str(scored_run_dir),
                    "steps_total": len(browser_results),
                    "steps_successful": sum(1 for row in browser_results if bool(row.get("success"))),
                }
            )
        except Exception as exc:
            run_status.append(
                {
                    "run_id": run_id,
                    "run_seed": run_seed,
                    "status": "failed",
                    "started_at": started_at,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "error": str(exc),
                }
            )
            if not continue_on_error:
                raise

    if not scorecards:
        raise RuntimeError("No successful runs produced scorecards.")

    aggregate = aggregate_scorecards(scorecards)
    _write_json(
        campaign_dir / "aggregate.scorecard.json",
        {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "campaign_id": campaign_id,
            "summary": aggregate,
        },
    )
    _write_json(
        campaign_dir / "campaign_manifest.json",
        {
            "campaign_id": campaign_id,
            "runs_attempted": runs_count,
            "runs_completed": len(scorecards),
            "run_status": run_status,
        },
    )

    run_index_rows = build_run_index_rows(scorecards)
    with (campaign_dir / "run_index.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "run_id",
                "competitor",
                "weighted_score",
                "credibility_weighted_score",
                "success_rate",
                "avg_elapsed_seconds",
                "avg_follow_up_prompts",
                "avg_quality_score",
                "evidence_coverage",
            ],
        )
        writer.writeheader()
        for row in run_index_rows:
            writer.writerow(row)

    report = render_campaign_report(
        campaign_id=campaign_id,
        aggregate=aggregate,
        runs_attempted=runs_count,
        runs_completed=len(scorecards),
    )
    (campaign_dir / "REPORT.md").write_text(report, encoding="utf-8")

    _write_json(publish_dir / "aggregate.scorecard.json", {"campaign_id": campaign_id, "summary": aggregate})
    _write_json(
        publish_dir / "campaign_manifest.json",
        {
            "campaign_id": campaign_id,
            "runs_attempted": runs_count,
            "runs_completed": len(scorecards),
            "run_status": run_status,
        },
    )
    (publish_dir / "REPORT.md").write_text(report, encoding="utf-8")
    with (publish_dir / "run_index.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "run_id",
                "competitor",
                "weighted_score",
                "credibility_weighted_score",
                "success_rate",
                "avg_elapsed_seconds",
                "avg_follow_up_prompts",
                "avg_quality_score",
                "evidence_coverage",
            ],
        )
        writer.writeheader()
        for row in run_index_rows:
            writer.writerow(row)

    return campaign_dir


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a multi-run head-to-head demo campaign.")
    parser.add_argument("--campaign-id", default="", help="Campaign id (default: UTC timestamp).")
    parser.add_argument("--runs-count", type=int, default=10, help="Number of runs to execute.")
    parser.add_argument("--task-pack", default=str(DEFAULT_TASK_PACK), help="Path to task pack JSON.")
    parser.add_argument(
        "--campaigns-dir",
        default=str(DEFAULT_CAMPAIGNS_DIR),
        help="Directory where campaign folders are created.",
    )
    parser.add_argument("--target", action="append", default=[], help="Target mapping competitor=url (repeatable).")
    parser.add_argument("--selectors-json", default="", help="Optional selectors config JSON.")
    parser.add_argument("--cdp-url", default="http://127.0.0.1:9222", help="Chrome DevTools endpoint.")
    parser.add_argument("--browser", default="chrome", choices=["chrome", "edge"], help="Browser for CDP launch.")
    parser.add_argument(
        "--launch-browser",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Auto-launch browser when CDP is unavailable.",
    )
    parser.add_argument("--type-delay-ms", type=int, default=20, help="Per-character typing delay.")
    parser.add_argument("--reply-timeout", type=float, default=90.0, help="Per-step reply timeout seconds.")
    parser.add_argument("--randomize-order", action=argparse.BooleanOptionalAction, default=True, help="Randomize execution plan.")
    parser.add_argument("--base-seed", type=int, default=42, help="Base seed for run randomization.")
    parser.add_argument("--runtime-root", default="", help="Runtime root for browser launch profile.")
    parser.add_argument(
        "--require-evidence",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require evidence for successful records.",
    )
    parser.add_argument(
        "--generate-blind-packs",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Generate blind judging packs for each scored run.",
    )
    parser.add_argument(
        "--continue-on-error",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Continue remaining runs if one run fails.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    campaign_id = str(args.campaign_id).strip() or datetime.now(timezone.utc).strftime("campaign-%Y%m%d-%H%M%S")
    selectors_path = Path(args.selectors_json).resolve() if str(args.selectors_json or "").strip() else None
    runtime_root = Path(args.runtime_root).resolve() if str(args.runtime_root or "").strip() else None
    if runtime_root is None:
        runtime_root = DEFAULT_BROWSER_RUNS_DIR.parents[1] / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)

    campaign_dir = run_campaign(
        campaign_id=campaign_id,
        runs_count=int(args.runs_count),
        task_pack_path=Path(args.task_pack).resolve(),
        target_pairs=list(args.target or []),
        selectors_json=selectors_path,
        cdp_url=str(args.cdp_url),
        browser=str(args.browser),
        launch_browser=bool(args.launch_browser),
        type_delay_ms=int(args.type_delay_ms),
        reply_timeout=float(args.reply_timeout),
        randomize_order=bool(args.randomize_order),
        base_seed=int(args.base_seed),
        runtime_root=runtime_root,
        campaigns_dir=Path(args.campaigns_dir).resolve(),
        require_evidence=bool(args.require_evidence),
        generate_blind_packs=bool(args.generate_blind_packs),
        continue_on_error=bool(args.continue_on_error),
    )
    print(f"Campaign completed: {campaign_dir}")
    print(f"  - {campaign_dir / 'campaign_manifest.json'}")
    print(f"  - {campaign_dir / 'aggregate.scorecard.json'}")
    print(f"  - {campaign_dir / 'run_index.csv'}")
    print(f"  - {campaign_dir / 'REPORT.md'}")
    print(f"  - {campaign_dir / 'publish'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

