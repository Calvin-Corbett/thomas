"""Agentic benchmark: local-first raw model vs Thomas OS comparison."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping, Sequence
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
from thomas.demo.agentic_benchmark_endurance import (
    load_endurance_ladder_pack,
    run_endurance_ladder,
)
from thomas.demo.agentic_benchmark_followup import (
    _build_artifact_follow_up_prompt,
    _merge_run_attempts,
    _missing_artifact_contract_items,
)
from thomas.demo.agentic_benchmark_helpers import (
    _pass_budget_for_mode,
    _pipeline_topology,
    _review_decision_for_candidate,
    _should_use_coding_pipeline,
)
from thomas.demo.agentic_benchmark_project import (
    load_project_pack,
    run_project_benchmark,
)

# Import helpers for re-export
from thomas.demo.agentic_benchmark_runners import (
    _run_raw_task,
    _run_thomas_api_task,
    _run_thomas_embedded_task,
)
from thomas.demo.agentic_benchmark_tool_agent import _run_tool_agent_task
from thomas.demo.agentic_benchmark_tracks import (
    TrackSpec,
    _build_baseline_track,
    _resolve_task_timeout_seconds,
    _track_validity_for_task_pack,
)
from thomas.demo.harness import (
    build_execution_plan,
    compute_summary,
    write_run_artifacts,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TASK_PACK = ROOT / "benchmarks" / "packs" / "capability" / "thomas_product_capability_smoke10_v1.json"
DEFAULT_RUNS_DIR = ROOT / "runtime" / "benchmarks" / "agentic-runs"

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
    "_run_tool_agent_task",
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


def _load_pack_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("Benchmark pack must be a JSON object.")
    return payload


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


def _background_completion_overrides_response_ack(
    run: Mapping[str, Any],
    checks: Mapping[str, Any],
) -> bool:
    if not bool(run.get("ok")):
        return False
    token_report = dict(run.get("token_report") or {})
    background = dict(token_report.get("background_task") or {})
    if str(background.get("state") or "").strip().lower() != "completed":
        return False

    reasons = [str(item or "").strip() for item in list(checks.get("reasons") or []) if str(item or "").strip()]
    if not reasons:
        return False
    if not all(reason.startswith("response missing expected text:") for reason in reasons):
        return False

    check_rows = dict(checks.get("checks") or {})
    if not check_rows:
        return False
    for name, ok in check_rows.items():
        if str(name).startswith("response_contains:"):
            continue
        if not bool(ok):
            return False
    return True


def _check_outcome_flags(checks: Mapping[str, Any], run: Mapping[str, Any]) -> dict[str, bool]:
    check_rows = dict(checks.get("checks") or {})
    response_checks = [bool(v) for k, v in check_rows.items() if str(k).startswith("response_contains:")]
    artifact_checks = [bool(v) for k, v in check_rows.items() if not str(k).startswith("response_contains:")]
    error_text = str(run.get("error") or "")
    return {
        "response_confirmed": (all(response_checks) if response_checks else True),
        "artifact_success": (all(artifact_checks) if artifact_checks else False),
        "timed_out": "time budget" in error_text.lower(),
        "runaway_guarded": "runaway budget usage" in error_text.lower(),
    }


async def _run_task_track_entry(
    *,
    task_pack: Mapping[str, Any],
    task: dict[str, Any],
    track: TrackSpec,
    args: argparse.Namespace,
    config: Any,
    run_id: str,
    artifact_root_rel: Path,
    workspace_root: Path,
    quality_min: int,
    quality_max: int,
    watch: bool,
) -> dict[str, Any]:
    task_id = str(task.get("id") or "").strip()
    context = {
        "run_id": run_id,
        "track": track.name,
        "artifact_dir": str((artifact_root_rel / track.name).as_posix()),
        "desktop_dir": str((Path.home() / "Desktop").as_posix()),
        "python_exe": f'"{sys.executable}"',
        "workspace": str(workspace_root.as_posix()),
    }
    rendered = render_task(task, context)
    prompt = str(rendered.get("prompt") or "")
    task_job_type = str(rendered.get("job_type") or task.get("job_type") or "benchmark").strip() or "benchmark"
    (workspace_root / Path(context["artifact_dir"])).mkdir(parents=True, exist_ok=True)
    watch_prefix = f"[{task_id}/{track.name}]"
    validity, invalid_reason = _track_validity_for_task_pack(task_pack=task_pack, track=track, args=args)
    timeout_seconds = _resolve_task_timeout_seconds(rendered, args)

    async def _execute_track(prompt_override: str | None = None) -> dict[str, Any]:
        active_prompt = str(prompt_override if prompt_override is not None else prompt)
        if track.kind == "raw":
            return await _run_raw_task(
                config,
                profile=track.profile,
                prompt=active_prompt,
                watch=watch,
                watch_prefix=watch_prefix,
            )
        if track.kind == "baseline_agent":
            return await _run_tool_agent_task(
                config,
                profile=track.profile,
                prompt=active_prompt,
                mode=track.mode,
                token_economy=track.token_economy,
                max_iterations=track.max_iterations,
                watch=watch,
                watch_prefix=watch_prefix,
            )
        if args.thomas_runner == "api":
            return await _run_thomas_api_task(
                api_base=args.thomas_api_base,
                api_token=args.thomas_api_token,
                profile=track.profile,
                prompt=active_prompt,
                mode=track.mode,
                token_economy=track.token_economy,
                max_iterations=track.max_iterations,
                job_type=task_job_type,
                watch=watch,
                watch_prefix=watch_prefix,
            )
        return await _run_thomas_embedded_task(
            config,
            profile=track.profile,
            prompt=active_prompt,
            mode=track.mode,
            token_economy=track.token_economy,
            max_iterations=track.max_iterations,
            job_type=task_job_type,
            watch=watch,
            watch_prefix=watch_prefix,
        )

    if validity != "valid":
        run = {
            "ok": False,
            "text": "",
            "error": "",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "tool_calls": 0,
            "elapsed_seconds": 0.0,
            "validity": validity,
            "invalid_reason": invalid_reason,
            "timeout_seconds": timeout_seconds,
        }
    else:
        try:
            if timeout_seconds is not None:
                run = await asyncio.wait_for(_execute_track(), timeout=timeout_seconds)
            else:
                run = await _execute_track()
        except TimeoutError:
            timeout_display = f"{timeout_seconds:.1f}".rstrip("0").rstrip(".") if timeout_seconds is not None else "0"
            run = {
                "ok": False,
                "text": "",
                "error": f"Task exceeded time budget of {timeout_display} seconds.",
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "tool_calls": 0,
                "elapsed_seconds": float(timeout_seconds or 0.0),
                "timeout_seconds": timeout_seconds,
            }

    checks = evaluate_task_success(rendered, response_text=str(run.get("text") or ""), workspace_root=workspace_root)
    follow_up_prompts = 0
    if validity == "valid" and str(task_pack.get("type") or "").strip() == "endurance_ladder":
        while follow_up_prompts < 2 and not bool(checks.get("success")):
            missing_files, missing_response_mentions = _missing_artifact_contract_items(checks)
            if not missing_files and not missing_response_mentions:
                break
            follow_up_prompts += 1
            follow_up_prompt = _build_artifact_follow_up_prompt(
                original_prompt=prompt,
                missing_files=missing_files,
                missing_response_mentions=missing_response_mentions,
            )
            follow_up_timeout = timeout_seconds
            if follow_up_timeout is not None:
                follow_up_timeout = min(float(follow_up_timeout), 60.0)
            try:
                if follow_up_timeout is not None:
                    follow_up_run = await asyncio.wait_for(
                        _execute_track(follow_up_prompt),
                        timeout=follow_up_timeout,
                    )
                else:
                    follow_up_run = await _execute_track(follow_up_prompt)
            except TimeoutError:
                timeout_display = (
                    f"{follow_up_timeout:.1f}".rstrip("0").rstrip(".") if follow_up_timeout is not None else "0"
                )
                follow_up_run = {
                    "ok": False,
                    "text": "",
                    "error": f"Task exceeded follow-up time budget of {timeout_display} seconds.",
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    "tool_calls": 0,
                    "elapsed_seconds": float(follow_up_timeout or 0.0),
                    "timeout_seconds": follow_up_timeout,
                }
            run = _merge_run_attempts(run, follow_up_run)
            checks = evaluate_task_success(
                rendered, response_text=str(run.get("text") or ""), workspace_root=workspace_root
            )
    outcome_flags = _check_outcome_flags(checks, run)
    success = bool(checks.get("success"))
    notes = []
    if not success and _background_completion_overrides_response_ack(run, checks):
        success = True
        notes.append("background_completion_override=response_ack_only")
    if not success and bool(outcome_flags["artifact_success"]) and not bool(outcome_flags["response_confirmed"]):
        success = True
        notes.append("artifact_success_without_confirmation_text")
    if validity != "valid":
        success = False
    if validity != "valid":
        notes.append(f"validity={validity}")
        if invalid_reason:
            notes.append(invalid_reason)
    err = str(run.get("error") or "").strip()
    if err:
        notes.append(f"runner_error={err}")
    notes.extend(list(checks.get("reasons") or []))
    notes_text = "; ".join(notes).strip()

    transcript_rel = str((Path("transcripts") / track.name / f"{task_id}.md").as_posix())
    transcript_body = "\n".join(
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
            f"- validity: {validity}",
            f"- invalid_reason: {invalid_reason}",
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
    record = {
        "task_id": task_id,
        "competitor": track.name,
        "success": bool(success),
        "elapsed_seconds": float(run.get("elapsed_seconds") or 0.0),
        "follow_up_prompts": int(follow_up_prompts),
        "quality_score": int(quality_score),
        "evidence": transcript_rel,
        "notes": notes_text,
        "validity": validity,
        "invalid_reason": invalid_reason,
        "artifact_success": bool(outcome_flags["artifact_success"]),
        "response_confirmed": bool(outcome_flags["response_confirmed"]),
        "timed_out": bool(outcome_flags["timed_out"]),
        "runaway_guarded": bool(outcome_flags["runaway_guarded"]),
        "runner_error_present": bool(str(run.get("error") or "").strip()),
        "captured_at": _now_iso(),
    }
    detailed_row = {
        "task_id": task_id,
        "track": track.name,
        "track_kind": track.kind,
        "mode": track.mode,
        "token_economy": track.token_economy,
        "max_iterations": track.max_iterations,
        "run": run,
        "checks": checks,
        "success": bool(success),
        "validity": validity,
        "invalid_reason": invalid_reason,
        "artifact_success": bool(outcome_flags["artifact_success"]),
        "response_confirmed": bool(outcome_flags["response_confirmed"]),
        "timed_out": bool(outcome_flags["timed_out"]),
        "runaway_guarded": bool(outcome_flags["runaway_guarded"]),
        "runner_error_present": bool(str(run.get("error") or "").strip()),
    }
    return {
        "task_id": task_id,
        "track": track.name,
        "record": record,
        "detailed_row": detailed_row,
        "transcript_rel": transcript_rel,
        "transcript_body": transcript_body,
    }


def _harness_pack(task_pack: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(task_pack.get("id") or "agentic-pack"),
        "name": str(task_pack.get("name") or "Agentic Benchmark Pack"),
        "version": int(task_pack.get("version") or 1),
        "type": str(task_pack.get("type") or "capability"),
        "family": str(task_pack.get("family") or ""),
        "description": str(task_pack.get("description") or ""),
        "protocol": list(task_pack.get("protocol") or []),
        "competitor_requirements": dict(task_pack.get("competitor_requirements") or {}),
        "report_metrics": list(task_pack.get("report_metrics") or []),
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

    task_pack_path = Path(args.task_pack).resolve()
    manifest = _load_pack_manifest(task_pack_path)
    pack_type = str(manifest.get("type") or "capability").strip() or "capability"

    run_id = str(args.run_id).strip() or datetime.now(timezone.utc).strftime("agentic-%Y%m%d-%H%M%S")
    workspace_root = Path(args.workspace).resolve()
    runs_dir = Path(args.runs_dir).resolve()

    if pack_type == "endurance_ladder":
        task_pack = load_endurance_ladder_pack(task_pack_path)
        quality_min = 1
        quality_max = 5
    elif pack_type == "project":
        task_pack = load_project_pack(task_pack_path)
        quality_min = int((task_pack.get("quality_scale") or {}).get("min", 1))
        quality_max = int((task_pack.get("quality_scale") or {}).get("max", 5))
    else:
        task_pack = load_agentic_task_pack(task_pack_path)
        quality_min = int((task_pack.get("quality_scale") or {}).get("min", 1))
        quality_max = int((task_pack.get("quality_scale") or {}).get("max", 5))

    baseline_track = _build_baseline_track(task_pack, args)
    thomas_name = str(args.thomas_name).strip() or "thomas_os"
    tracks: list[TrackSpec] = []
    if not bool(args.skip_baseline):
        tracks.append(baseline_track)
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

    if pack_type == "endurance_ladder":
        return await run_endurance_ladder(
            args=args,
            config=config,
            task_pack=task_pack,
            tracks=tracks,
            run_id=run_id,
            workspace_root=workspace_root,
            runs_dir=runs_dir,
            quality_min=quality_min,
            quality_max=quality_max,
            run_task_entry=_run_task_track_entry,
        )

    if pack_type == "project":
        return await run_project_benchmark(
            args=args,
            config=config,
            task_pack=task_pack,
            tracks=tracks,
            run_id=run_id,
            workspace_root=workspace_root,
            runs_dir=runs_dir,
            quality_min=quality_min,
            quality_max=quality_max,
            run_task_entry=_run_task_track_entry,
        )

    baseline_name = baseline_track.name
    artifact_root_rel = Path("runtime") / "agentic_bench" / run_id
    records: list[dict[str, Any]] = []
    detailed_rows: list[dict[str, Any]] = []
    transcript_blobs: dict[str, str] = {}
    watch = bool(getattr(args, "watch", False))
    concurrency = max(1, int(getattr(args, "concurrency", 1) or 1))
    job_specs: list[tuple[int, dict[str, Any], TrackSpec]] = []
    for idx, task in enumerate(list(task_pack.get("tasks") or [])):
        for track in tracks:
            job_specs.append((idx, task, track))

    if concurrency == 1:
        for _idx, task, track in job_specs:
            result = await _run_task_track_entry(
                task_pack=task_pack,
                task=task,
                track=track,
                args=args,
                config=config,
                run_id=run_id,
                artifact_root_rel=artifact_root_rel,
                workspace_root=workspace_root,
                quality_min=quality_min,
                quality_max=quality_max,
                watch=watch,
            )
            transcript_blobs[str(result["transcript_rel"])] = str(result["transcript_body"])
            records.append(dict(result["record"]))
            detailed_rows.append(dict(result["detailed_row"]))
    else:
        semaphore = asyncio.Semaphore(concurrency)

        async def _bounded_run(
            order_idx: int,
            task: dict[str, Any],
            track: TrackSpec,
        ) -> tuple[int, dict[str, Any]]:
            async with semaphore:
                result = await _run_task_track_entry(
                    task_pack=task_pack,
                    task=task,
                    track=track,
                    args=args,
                    config=config,
                    run_id=run_id,
                    artifact_root_rel=artifact_root_rel,
                    workspace_root=workspace_root,
                    quality_min=quality_min,
                    quality_max=quality_max,
                    watch=watch,
                )
                return order_idx, result

        job_results = await asyncio.gather(
            *[_bounded_run(order_idx, task, track) for order_idx, task, track in job_specs]
        )
        for _order_idx, result in sorted(job_results, key=lambda item: item[0]):
            transcript_blobs[str(result["transcript_rel"])] = str(result["transcript_body"])
            records.append(dict(result["record"]))
            detailed_rows.append(dict(result["detailed_row"]))

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
            "task_timeout_seconds": float(getattr(args, "task_timeout_seconds", 0.0) or 0.0),
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
    parser.add_argument("--baseline-name", default="", help="Optional competitor label for the baseline track.")
    parser.add_argument(
        "--baseline-runner",
        choices=("auto", "raw", "tool-agent"),
        default="auto",
        help="Baseline lane to run. `auto` uses `tool-agent` for tool-required packs and `raw` otherwise.",
    )
    parser.add_argument("--baseline-mode", choices=("fast", "auto", "thinking"), default="auto")
    parser.add_argument("--baseline-token-economy", choices=("cheap", "optimal", "max"), default="optimal")
    parser.add_argument("--baseline-max-iterations", type=int, default=None)
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
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Number of benchmark task entries to run concurrently (default: 1).",
    )
    parser.add_argument(
        "--task-timeout-seconds",
        type=float,
        default=0.0,
        help="Optional per-task timeout override. When set, the lower of this value and the pack budget is used.",
    )
    parser.add_argument(
        "--endurance-rung",
        default="",
        help="Optional endurance rung id when running an endurance ladder pack (default: first rung).",
    )
    parser.add_argument(
        "--endurance-poll-seconds",
        type=float,
        default=5.0,
        help="Polling interval in seconds for endurance repo-state tracking.",
    )
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
    for artifact_name in (
        "summary.json",
        "scorecard.json",
        "before_after.delta.json",
        "benchmark_results.raw.json",
        "report.md",
    ):
        artifact_path = run_dir / artifact_name
        if artifact_path.exists():
            print(f"  - {artifact_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
