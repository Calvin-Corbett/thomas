"""Agentic benchmark: local-first raw model vs Thomas OS comparison."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.core.config import load_config
from thomas.demo.agentic_benchmark_core import (
    _ensure_usage_telemetry,
    _estimate_text_tokens,
    _extract_reported_first_token_ms,
    _extract_usage_from_token_report,
    _safe_float,
    _select_elapsed_seconds,
    _select_optional_elapsed_seconds,
    apply_template_context,
    compute_before_after_delta,
    evaluate_task_success,
    load_agentic_task_pack,
    render_task,
)
from thomas.demo.agentic_benchmark_helpers import (
    _pass_budget_for_mode,
    _pipeline_topology,
    _review_decision_for_candidate,
    _should_use_coding_pipeline,
)

# Import helpers for re-export
from thomas.demo.agentic_benchmark_runners import (
    _run_raw_task,
    _run_thomas_api_task,
    _run_thomas_embedded_task,
)
from thomas.demo.harness import (
    build_execution_plan,
    compute_summary,
    write_run_artifacts,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TASK_PACK = ROOT / "demo" / "task_pack.agentic.local.json"
DEFAULT_RUNS_DIR = ROOT / "demo" / "agentic-runs"

__all__ = [
    "apply_template_context",
    "compute_before_after_delta",
    "evaluate_task_success",
    "load_agentic_task_pack",
    "main",
    "parse_args",
    "render_task",
    "run_agentic_benchmark",
    "_ensure_usage_telemetry",
    "_estimate_text_tokens",
    "_extract_reported_first_token_ms",
    "_extract_usage_from_token_report",
    "_pass_budget_for_mode",
    "_pipeline_topology",
    "_resolve_config_path",
    "_review_decision_for_candidate",
    "_run_thomas_api_task",
    "_safe_float",
    "_select_elapsed_seconds",
    "_select_optional_elapsed_seconds",
    "_should_use_coding_pipeline",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _resolve_config_path(config_arg: str) -> Path | None:
    text = str(config_arg or "").strip()
    if text:
        return Path(text).resolve()
    env_path = str(os.environ.get("THOMAS_CONFIG", "")).strip()
    if env_path:
        return None
    repo_default = ROOT / "thomas.toml"
    if repo_default.exists():
        return repo_default.resolve()
    return None


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


def _harness_pack(task_pack: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(task_pack.get("id") or "agentic-pack"),
        "name": str(task_pack.get("name") or "Agentic Benchmark Pack"),
        "version": int(task_pack.get("version") or 1),
        "description": str(task_pack.get("description") or ""),
        "protocol": list(task_pack.get("protocol") or []),
        "weights": dict(task_pack.get("weights") or {}),
        "quality_scale": dict(task_pack.get("quality_scale") or {"min": 1, "max": 5}),
        "tasks": [
            {
                "id": str(t.get("id") or ""),
                "title": str(t.get("title") or ""),
                "prompt": str(t.get("prompt") or ""),
                "success_criteria": str(t.get("success_criteria") or ""),
                "time_budget_seconds": t.get("time_budget_seconds"),
            }
            for t in (task_pack.get("tasks") or [])
        ],
    }


async def run_agentic_benchmark(args: argparse.Namespace) -> Path:
    config_path = _resolve_config_path(str(args.config or ""))
    config = load_config(config_path)

    task_pack = load_agentic_task_pack(Path(args.task_pack).resolve())
    quality_min = int((task_pack.get("quality_scale") or {}).get("min", 1))
    quality_max = int((task_pack.get("quality_scale") or {}).get("max", 5))

    run_id = str(args.run_id).strip() or datetime.now(timezone.utc).strftime("agentic-%Y%m%d-%H%M%S")
    workspace_root = Path(args.workspace).resolve()
    runs_dir = Path(args.runs_dir).resolve()
    artifact_root_rel = Path("runtime") / "agentic_bench" / run_id

    baseline_name = str(args.baseline_name).strip() or "baseline_raw"
    thomas_name = str(args.thomas_name).strip() or "thomas_os"
    tracks: list[TrackSpec] = []
    if not bool(args.skip_baseline):
        tracks.append(TrackSpec(name=baseline_name, kind="raw", profile=args.profile))
    if not bool(args.skip_thomas):
        tracks.append(
            TrackSpec(
                name=thomas_name,
                kind="thomas",
                profile=args.profile,
                mode=args.thomas_mode,
                token_economy=args.thomas_token_economy,
                max_iterations=args.max_iterations,
            )
        )
    if not tracks:
        raise ValueError("Nothing to run: both baseline and thomas tracks are disabled.")

    if bool(args.thomas_max_mode):
        for track in tracks:
            if track.kind != "thomas":
                continue
            track.token_economy = "max"
            if args.thomas_runner == "api":
                track.mode = "swarm"
            else:
                track.mode = "thinking"
            if track.max_iterations is None:
                track.max_iterations = 20

    if args.thomas_runner == "embedded":
        for track in tracks:
            if track.kind == "thomas" and track.mode == "swarm":
                raise ValueError("mode=swarm requires --thomas-runner api")

    records: list[dict[str, Any]] = []
    detailed_rows: list[dict[str, Any]] = []
    transcript_blobs: dict[str, str] = {}
    watch = bool(getattr(args, "watch", False))

    for task in list(task_pack.get("tasks") or []):
        task_id = str(task.get("id") or "").strip()
        for track in tracks:
            context = {
                "run_id": run_id,
                "track": track.name,
                "artifact_dir": str((artifact_root_rel / track.name).as_posix()),
                "workspace": str(workspace_root.as_posix()),
            }
            rendered = render_task(task, context)
            prompt = str(rendered.get("prompt") or "")
            (workspace_root / Path(context["artifact_dir"])).mkdir(parents=True, exist_ok=True)
            watch_prefix = f"[{task_id}/{track.name}]"

            if track.kind == "raw":
                run = await _run_raw_task(
                    config,
                    profile=track.profile,
                    prompt=prompt,
                    watch=watch,
                    watch_prefix=watch_prefix,
                )
            elif args.thomas_runner == "api":
                run = await _run_thomas_api_task(
                    api_base=args.thomas_api_base,
                    api_token=args.thomas_api_token,
                    profile=track.profile,
                    prompt=prompt,
                    mode=track.mode,
                    token_economy=track.token_economy,
                    max_iterations=track.max_iterations,
                    watch=watch,
                    watch_prefix=watch_prefix,
                )
            else:
                run = await _run_thomas_embedded_task(
                    config,
                    profile=track.profile,
                    prompt=prompt,
                    mode=track.mode,
                    token_economy=track.token_economy,
                    max_iterations=track.max_iterations,
                    watch=watch,
                    watch_prefix=watch_prefix,
                )

            checks = evaluate_task_success(
                rendered,
                response_text=str(run.get("text") or ""),
                workspace_root=workspace_root,
            )
            success = bool(run.get("ok")) and bool(checks.get("success"))
            notes = []
            err = str(run.get("error") or "").strip()
            if err:
                notes.append(f"runner_error={err}")
            notes.extend(list(checks.get("reasons") or []))
            notes_text = "; ".join(notes).strip()

            transcript_rel = str((Path("transcripts") / track.name / f"{task_id}.md").as_posix())
            transcript_blobs[transcript_rel] = "\n".join(
                [
                    f"# Task {task_id} - {track.name}",
                    "",
                    f"- run_id: {run_id}",
                    f"- track_kind: {track.kind}",
                    f"- profile: {track.profile}",
                    f"- mode: {track.mode if track.kind == 'thomas' else 'raw'}",
                    f"- token_economy: {track.token_economy if track.kind == 'thomas' else 'n/a'}",
                    f"- elapsed_seconds: {run.get('elapsed_seconds')}",
                    f"- first_token_seconds: {run.get('first_token_seconds')}",
                    f"- first_text_delta_seconds: {run.get('first_text_delta_seconds')}",
                    f"- first_stream_event_seconds: {run.get('first_stream_event_seconds')}",
                    f"- setup_elapsed_seconds: {run.get('setup_elapsed_seconds')}",
                    f"- stream_event_count: {run.get('stream_event_count')}",
                    f"- text_event_count: {run.get('text_event_count')}",
                    f"- success: {str(success).lower()}",
                    f"- tool_calls: {run.get('tool_calls')}",
                    f"- usage: {json.dumps(run.get('usage') or {}, ensure_ascii=False)}",
                    "",
                    "## Prompt",
                    "",
                    "```text",
                    prompt,
                    "```",
                    "",
                    "## Response",
                    "",
                    "```text",
                    str(run.get("text") or ""),
                    "```",
                    "",
                    "## Checks",
                    "",
                    "```json",
                    json.dumps(checks, ensure_ascii=False, indent=2),
                    "```",
                    "",
                ]
            )

            quality_score = quality_max if success else quality_min
            records.append(
                {
                    "task_id": task_id,
                    "competitor": track.name,
                    "success": bool(success),
                    "elapsed_seconds": float(run.get("elapsed_seconds") or 0.0),
                    "follow_up_prompts": 0,
                    "quality_score": int(quality_score),
                    "evidence": transcript_rel,
                    "notes": notes_text,
                    "captured_at": _now_iso(),
                }
            )
            detailed_rows.append(
                {
                    "task_id": task_id,
                    "track": track.name,
                    "track_kind": track.kind,
                    "mode": track.mode,
                    "token_economy": track.token_economy,
                    "max_iterations": track.max_iterations,
                    "run": run,
                    "checks": checks,
                    "success": bool(success),
                }
            )

    harness_pack = _harness_pack(task_pack)
    competitors = [t.name for t in tracks]
    execution_plan = build_execution_plan(
        task_pack=harness_pack,
        competitors=competitors,
        randomize=False,
        seed=None,
    )
    summary = compute_summary(harness_pack, records)

    run_dir = write_run_artifacts(
        runs_dir=runs_dir,
        run_id=run_id,
        task_pack=harness_pack,
        competitors=competitors,
        execution_plan=execution_plan,
        randomized_order=False,
        random_seed=None,
        require_evidence=False,
        records=records,
        summary=summary,
    )

    for rel, body in transcript_blobs.items():
        target = run_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")

    before_after = compute_before_after_delta(
        summary,
        baseline_name=baseline_name,
        thomas_name=thomas_name,
    )

    _write_json(run_dir / "benchmark_results.raw.json", detailed_rows)
    _write_json(run_dir / "task_pack.agentic.snapshot.json", task_pack)
    _write_json(
        run_dir / "agentic_benchmark.config.json",
        {
            "created_at": _now_iso(),
            "profile": args.profile,
            "workspace": str(workspace_root),
            "thomas_runner": args.thomas_runner,
            "thomas_api_base": str(args.thomas_api_base or ""),
            "thomas_mode": str(args.thomas_mode or ""),
            "thomas_token_economy": str(args.thomas_token_economy or ""),
            "thomas_max_mode": bool(args.thomas_max_mode),
            "max_iterations": args.max_iterations,
            "watch": watch,
            "baseline_enabled": not bool(args.skip_baseline),
            "thomas_enabled": not bool(args.skip_thomas),
            "artifact_root": str(artifact_root_rel.as_posix()),
            "config_path": str(config_path) if config_path else "",
        },
    )
    _write_json(run_dir / "before_after.delta.json", before_after)
    return run_dir


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local-first agentic benchmark: raw model vs Thomas OS.")
    parser.add_argument("--task-pack", default=str(DEFAULT_TASK_PACK), help="Path to benchmark task pack JSON.")
    parser.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR), help="Output directory for benchmark runs.")
    parser.add_argument("--run-id", default="", help="Optional run id (default: UTC timestamp).")
    parser.add_argument("--config", default="", help="Optional path to thomas.toml.")
    parser.add_argument("--workspace", default=".", help="Workspace root for file-based checks.")
    parser.add_argument("--profile", default="local", help="Model profile to benchmark (default: local).")
    parser.add_argument("--baseline-name", default="baseline_raw", help="Competitor label for raw baseline.")
    parser.add_argument("--thomas-name", default="thomas_os", help="Competitor label for Thomas track.")
    parser.add_argument("--skip-baseline", action="store_true", help="Skip raw baseline track.")
    parser.add_argument("--skip-thomas", action="store_true", help="Skip Thomas track.")
    parser.add_argument("--thomas-runner", choices=("embedded", "api"), default="embedded")
    parser.add_argument(
        "--thomas-api-base", default="http://127.0.0.1:8899", help="Thomas API base URL when --thomas-runner=api."
    )
    parser.add_argument("--thomas-api-token", default="", help="Thomas API bearer token for remote mode.")
    parser.add_argument("--thomas-mode", choices=("fast", "auto", "thinking", "swarm"), default="auto")
    parser.add_argument("--thomas-token-economy", choices=("cheap", "optimal", "max"), default="optimal")
    parser.add_argument(
        "--thomas-max-mode",
        action="store_true",
        help="Enable high-budget Thomas mode (max token economy; swarm via API runner).",
    )
    parser.add_argument("--max-iterations", type=int, default=None, help="Optional max iterations for Thomas track.")
    parser.add_argument("--watch", action="store_true", help="Stream live model/tool output while benchmark runs.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not str(args.thomas_api_token or "").strip():
        env_token = str(__import__("os").environ.get("THOMAS_API_TOKEN", "")).strip()
        if env_token:
            args.thomas_api_token = env_token
    run_dir = asyncio.run(run_agentic_benchmark(args))
    print(f"Agentic benchmark completed: {run_dir}")
    print(f"  - {run_dir / 'scorecard.json'}")
    print(f"  - {run_dir / 'before_after.delta.json'}")
    print(f"  - {run_dir / 'benchmark_results.raw.json'}")
    print(f"  - {run_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
