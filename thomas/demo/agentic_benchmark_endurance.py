from __future__ import annotations

import asyncio
import copy
import json
import os
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from thomas.core.benchmark_lane import (
    BENCHMARK_REPO_ROOT_ENV,
    BENCHMARK_SINGLE_AGENT_ENV,
    BENCHMARK_WORKBOARD_PATH_ENV,
)
from thomas.demo.agentic_benchmark_endurance_contract import (
    evaluate_endurance_report_contract as _evaluate_endurance_report_contract,
)
from thomas.demo.agentic_benchmark_endurance_contract import (
    snapshot_changed as _snapshot_changed,
)
from thomas.demo.agentic_benchmark_endurance_runtime import (
    SNAPSHOT_IGNORED_PREFIXES as _SNAPSHOT_IGNORED_PREFIXES,
)
from thomas.demo.agentic_benchmark_endurance_runtime import (
    _snapshot_ignore as _runtime_snapshot_ignore,
)
from thomas.demo.agentic_benchmark_endurance_runtime import (
    capture_repo_snapshot,
    copy_workspace_snapshot,
    monitor_repo_progress,
)
from thomas.demo.agentic_benchmark_endurance_runtime import (
    isolated_thomas_server as _isolated_thomas_server,
)
from thomas.demo.agentic_benchmark_endurance_runtime import (
    new_commits as _new_commits,
)
from thomas.demo.agentic_benchmark_endurance_runtime import (
    read_endurance_report as _read_endurance_report,
)
from thomas.demo.agentic_benchmark_endurance_runtime import (
    timeline_summary as _timeline_summary,
)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_endurance_ladder_pack(path: Path) -> dict[str, Any]:
    data = _read_json(path)
    if not isinstance(data, dict):
        raise ValueError("Endurance pack must be a JSON object.")
    if str(data.get("type") or "").strip() != "endurance_ladder":
        raise ValueError("Endurance pack type must be `endurance_ladder`.")

    rungs = list(data.get("rungs") or [])
    if not rungs:
        raise ValueError("Endurance ladder must define at least one rung.")

    normalized_rungs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for idx, rung in enumerate(rungs, start=1):
        if not isinstance(rung, dict):
            raise ValueError(f"rungs[{idx}] must be an object.")
        rung_id = str(rung.get("id") or "").strip()
        minutes = int(rung.get("time_budget_minutes") or 0)
        if not rung_id:
            raise ValueError(f"rungs[{idx}] is missing id.")
        if rung_id in seen_ids:
            raise ValueError(f"Duplicate endurance rung id: {rung_id}")
        if minutes <= 0:
            raise ValueError(f"rungs[{idx}] has invalid time_budget_minutes: {minutes}")
        seen_ids.add(rung_id)
        normalized_rungs.append({"id": rung_id, "time_budget_minutes": minutes})

    return {
        "id": str(data.get("id") or path.stem),
        "name": str(data.get("name") or "Endurance Ladder"),
        "version": int(data.get("version") or 1),
        "type": "endurance_ladder",
        "family": str(data.get("family") or "").strip(),
        "description": str(data.get("description") or "").strip(),
        "competitor_requirements": dict(data.get("competitor_requirements") or {}),
        "starting_snapshot_policy": dict(data.get("starting_snapshot_policy") or {}),
        "stop_conditions": [
            str(item or "").strip()
            for item in list(data.get("stop_conditions") or [])
            if str(item or "").strip()
        ],
        "task_contract": dict(data.get("task_contract") or {}),
        "report_metrics": [
            str(item or "").strip()
            for item in list(data.get("report_metrics") or [])
            if str(item or "").strip()
        ],
        "rungs": normalized_rungs,
    }


def _resolve_rung(task_pack: Mapping[str, Any], rung_id: str | None) -> dict[str, Any]:
    rungs = list(task_pack.get("rungs") or [])
    if not rungs:
        raise ValueError("Endurance ladder has no rungs.")
    wanted = str(rung_id or "").strip()
    if not wanted:
        return dict(rungs[0])
    for rung in rungs:
        if str(rung.get("id") or "").strip() == wanted:
            return dict(rung)
    raise ValueError(f"Unknown endurance rung: {wanted}")


def _snapshot_ignore(src_root: Path, current_dir: str, names: list[str]) -> list[str]:
    return _runtime_snapshot_ignore(src_root, current_dir, names)


def build_endurance_task(
    *,
    rung: Mapping[str, Any],
    task_contract: Mapping[str, Any],
    report_relpath: str,
) -> dict[str, Any]:
    rules = [
        str(item or "").strip()
        for item in list(task_contract.get("rules") or [])
        if str(item or "").strip()
    ]
    outputs = [
        str(item or "").strip()
        for item in list(task_contract.get("required_final_output") or [])
        if str(item or "").strip()
    ]
    lines = [
        "You are working in a dirty Thomas repo snapshot.",
        "",
        f"Time budget: {int(rung.get('time_budget_minutes') or 0)} minutes.",
        f"Goal: {str(task_contract.get('goal') or '').strip()}",
        "",
        "Rules:",
    ]
    lines.extend(f"- {rule}" for rule in rules)
    lines.extend(
        [
            "",
            "Before finishing, write a JSON report to this exact relative path:",
            f"- {report_relpath}",
            "",
            "Do not stop after only inspection, planning, or a status update.",
            "If you cannot land a commit, you must still write the JSON report with an empty commit list and concrete blockers.",
            "The task is incomplete until that JSON report exists.",
            "",
            "That JSON must include these keys:",
            "- commit_shas_created",
            "- verification_runs",
            "- remaining_blockers",
            "- best_next_step",
            "- recovery_actions",
            "- guardrail_violation_count",
            "- protected_file_attempt_count",
        ]
    )
    if outputs:
        lines.extend(["", "Required final output fields:"])
        lines.extend(f"- {item}" for item in outputs)
    lines.extend(["", f"In your final response, mention: {report_relpath}"])
    return {
        "id": str(rung.get("id") or "endurance"),
        "title": f"Endurance rung {str(rung.get('id') or '')}",
        "prompt": "\n".join(lines).strip(),
        "job_type": "coding",
        "success_criteria": "Write the required endurance JSON report and mention its path in the final response.",
        "time_budget_seconds": int(rung.get("time_budget_minutes") or 0) * 60,
        "success": {
            "response_contains": [report_relpath],
            "required_files": [report_relpath],
            "required_file_contains": {
                report_relpath: "\"commit_shas_created\"",
            },
        },
    }


@contextmanager
def _temporary_benchmark_env(*, home_dir: Path, workspace_root: Path, run_id: str, track_name: str):
    workboard_path = workspace_root / "plans" / "thomas" / "WORKBOARD.md"
    env_values = {
        "THOMAS_DATA_DIR": str(home_dir),
        "THOMAS_HOME": str(home_dir),
        "THOMAS_STATE_DIR": str(home_dir),
        "THOMAS_RUNTIME_DIR": str(home_dir / "runtime"),
        "THOMAS_ARTIFACT_DIR": str(home_dir / "artifacts"),
        "THOMAS_ARTIFACTS_DIR": str(home_dir / "artifacts"),
        "THOMAS_TASK_MANAGER_LOOP_ENABLED": "0",
        BENCHMARK_SINGLE_AGENT_ENV: "1",
        BENCHMARK_REPO_ROOT_ENV: str(workspace_root),
        BENCHMARK_WORKBOARD_PATH_ENV: str(workboard_path),
        "THOMAS_BENCHMARK_RUN_ID": run_id,
        "THOMAS_BENCHMARK_TRACK": track_name,
    }
    previous = {key: os.environ.get(key) for key in env_values}
    try:
        for key, value in env_values.items():
            os.environ[key] = value
        yield
    finally:
        for key, old_value in previous.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def _metric_value(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _metric_winners(
    competitor_rows: Mapping[str, Mapping[str, Any]],
    key: str,
    *,
    higher_is_better: bool,
) -> list[str]:
    values: list[tuple[str, float]] = []
    for name, payload in competitor_rows.items():
        metric = _metric_value(payload.get(key))
        if metric is None:
            continue
        values.append((name, metric))
    if not values:
        return []
    target = max(metric for _, metric in values) if higher_is_better else min(metric for _, metric in values)
    return sorted(name for name, metric in values if metric == target)


def build_endurance_summary(
    *,
    run_id: str,
    task_pack: Mapping[str, Any],
    rung: Mapping[str, Any],
    competitor_rows: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "task_pack_id": str(task_pack.get("id") or ""),
        "task_pack_version": int(task_pack.get("version") or 1),
        "task_pack_type": str(task_pack.get("type") or ""),
        "rung": {
            "id": str(rung.get("id") or ""),
            "time_budget_minutes": int(rung.get("time_budget_minutes") or 0),
        },
        "competitors": dict(competitor_rows),
        "metric_winners": {
            "commit_count": _metric_winners(competitor_rows, "commit_count", higher_is_better=True),
            "files_cleaned": _metric_winners(competitor_rows, "files_cleaned", higher_is_better=True),
            "dirty_lines_drained": _metric_winners(competitor_rows, "dirty_lines_drained", higher_is_better=True),
            "time_to_first_commit": _metric_winners(
                competitor_rows,
                "time_to_first_commit",
                higher_is_better=False,
            ),
            "guardrail_violation_count": _metric_winners(
                competitor_rows,
                "guardrail_violation_count",
                higher_is_better=False,
            ),
        },
    }


def build_endurance_report(summary: Mapping[str, Any]) -> str:
    rung = dict(summary.get("rung") or {})
    rows = dict(summary.get("competitors") or {})
    winners = dict(summary.get("metric_winners") or {})
    lines = [
        f"# Endurance Report: {summary.get('run_id')}",
        "",
        f"Task pack: `{summary.get('task_pack_id')}`",
        f"Rung: `{rung.get('id')}` ({rung.get('time_budget_minutes')} minutes)",
        "",
        "## Metric Panels",
        "",
    ]
    for name, payload in rows.items():
        lines.extend(
            [
                f"### {name}",
                f"- Validity: {payload.get('validity')}",
                f"- Invalid reason: {payload.get('invalid_reason') or 'n/a'}",
                f"- Report contract success: {payload.get('report_contract_success')}",
                f"- Productive progress: {payload.get('productive_progress')}",
                f"- Actionable no-progress report: {payload.get('actionable_no_progress')}",
                f"- Follow-up prompts: {payload.get('follow_up_prompts')}",
                f"- Commit count: {payload.get('commit_count')}",
                f"- Verification pass count: {payload.get('verification_pass_count')}",
                f"- Verification fail count: {payload.get('verification_fail_count')}",
                f"- Files cleaned: {payload.get('files_cleaned')}",
                f"- Dirty lines drained: {payload.get('dirty_lines_drained')}",
                f"- Time to first real progress: {payload.get('time_to_first_real_progress')}",
                f"- Time to first commit: {payload.get('time_to_first_commit')}",
                f"- Stall count: {payload.get('stall_count')}",
                f"- Longest stall seconds: {payload.get('longest_stall_seconds')}",
                f"- Recovery count: {payload.get('recovery_count')}",
                f"- Guardrail violation count: {payload.get('guardrail_violation_count')}",
                f"- Protected-file attempt count: {payload.get('protected_file_attempt_count')}",
                f"- Tool call count: {payload.get('tool_call_count')}",
                f"- Token usage total: {payload.get('token_usage', {}).get('total_tokens')}",
                f"- Remaining blocker count: {payload.get('remaining_blocker_count')}",
                f"- Final dirty file count: {payload.get('final_dirty_state', {}).get('dirty_file_count')}",
                f"- Source repo changed: {payload.get('source_repo_changed')}",
                f"- Live source repo changed: {payload.get('live_source_repo_changed')}",
                "",
            ]
        )
    lines.extend(
        [
            "## Metric Winners",
            "",
            f"- Commit count: {', '.join(winners.get('commit_count') or []) or 'n/a'}",
            f"- Files cleaned: {', '.join(winners.get('files_cleaned') or []) or 'n/a'}",
            f"- Dirty lines drained: {', '.join(winners.get('dirty_lines_drained') or []) or 'n/a'}",
            f"- Time to first commit: {', '.join(winners.get('time_to_first_commit') or []) or 'n/a'}",
            f"- Guardrail violation count: {', '.join(winners.get('guardrail_violation_count') or []) or 'n/a'}",
            "",
        ]
    )
    return "\n".join(lines).strip() + "\n"


async def run_endurance_ladder(
    *,
    args: Any,
    config: Any,
    task_pack: Mapping[str, Any],
    tracks: Sequence[Any],
    run_id: str,
    workspace_root: Path,
    runs_dir: Path,
    quality_min: int,
    quality_max: int,
    run_task_entry: Callable[..., Awaitable[dict[str, Any]]],
) -> Path:
    rung = _resolve_rung(task_pack, getattr(args, "endurance_rung", ""))
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    source_snapshot_root = run_dir / "source-snapshot"
    copy_workspace_snapshot(workspace_root, source_snapshot_root)

    artifact_root_rel = Path("runtime") / "agentic_bench" / run_id
    ignored_prefixes = [artifact_root_rel.as_posix()]
    live_source_ignored_prefixes = list(
        dict.fromkeys(
            [
                *_SNAPSHOT_IGNORED_PREFIXES,
                (Path("runtime") / "benchmarks" / "agentic-runs" / run_id).as_posix(),
                artifact_root_rel.as_posix(),
            ]
        )
    )
    poll_seconds = max(1.0, float(getattr(args, "endurance_poll_seconds", 5.0) or 5.0))

    competitor_rows: dict[str, dict[str, Any]] = {}
    detailed_rows: list[dict[str, Any]] = []
    transcript_blobs: dict[str, str] = {}

    for track in tracks:
        track_name = str(getattr(track, "name", "") or "")
        track_kind = str(getattr(track, "kind", "") or "")
        track_workspace = run_dir / "workspaces" / track_name
        copy_workspace_snapshot(source_snapshot_root, track_workspace)

        benchmark_home = run_dir / "track-state" / track_name
        benchmark_home.mkdir(parents=True, exist_ok=True)
        report_relpath = (artifact_root_rel / track_name / "endurance_report.json").as_posix()
        task = build_endurance_task(
            rung=rung,
            task_contract=dict(task_pack.get("task_contract") or {}),
            report_relpath=report_relpath,
        )
        track_config = copy.deepcopy(config)
        track_config.tools.sandbox_root = str(track_workspace)

        source_snapshot_before = capture_repo_snapshot(source_snapshot_root, [])
        live_source_snapshot_before = capture_repo_snapshot(workspace_root, live_source_ignored_prefixes)
        initial_snapshot = capture_repo_snapshot(track_workspace, ignored_prefixes)
        stop_event = asyncio.Event()
        monitor_task = asyncio.create_task(
            monitor_repo_progress(
                track_workspace,
                ignored_prefixes,
                stop_event,
                poll_seconds=poll_seconds,
            )
        )

        track_args = copy.copy(args)
        run_kwargs = {
            "task_pack": dict(task_pack),
            "task": task,
            "track": track,
            "args": track_args,
            "config": track_config,
            "run_id": run_id,
            "artifact_root_rel": artifact_root_rel,
            "workspace_root": track_workspace,
            "quality_min": quality_min,
            "quality_max": quality_max,
            "watch": bool(getattr(args, "watch", False)),
        }
        with _temporary_benchmark_env(
            home_dir=benchmark_home,
            workspace_root=track_workspace,
            run_id=run_id,
            track_name=track_name,
        ):
            use_api_runner = track_kind == "thomas" and str(getattr(args, "thomas_runner", "")).strip() == "api"
            if use_api_runner:
                with _isolated_thomas_server(
                    track_workspace,
                    benchmark_home,
                    extra_env={
                        "THOMAS_TASK_MANAGER_LOOP_ENABLED": "0",
                        BENCHMARK_SINGLE_AGENT_ENV: "1",
                        BENCHMARK_REPO_ROOT_ENV: str(track_workspace),
                        BENCHMARK_WORKBOARD_PATH_ENV: str(track_workspace / "plans" / "thomas" / "WORKBOARD.md"),
                        "THOMAS_BENCHMARK_RUN_ID": run_id,
                        "THOMAS_BENCHMARK_TRACK": track_name,
                    },
                ) as base_url:
                    track_args.thomas_runner = "api"
                    track_args.thomas_api_base = base_url
                    track_args.thomas_api_token = ""
                    result = await run_task_entry(**run_kwargs)
            else:
                result = await run_task_entry(**run_kwargs)

        stop_event.set()
        timeline = await monitor_task
        source_snapshot_after = capture_repo_snapshot(source_snapshot_root, [])
        live_source_snapshot_after = capture_repo_snapshot(workspace_root, live_source_ignored_prefixes)
        final_snapshot = capture_repo_snapshot(track_workspace, ignored_prefixes)
        report_payload = _read_endurance_report(track_workspace / report_relpath)
        commits = _new_commits(track_workspace, str(initial_snapshot.get("head") or ""))
        report_contract = _evaluate_endurance_report_contract(report_payload, commits)
        timeline_metrics = _timeline_summary(initial_snapshot, timeline)

        verification_runs = list(report_contract.get("verification_runs") or [])
        verification_pass_count = sum(1 for item in verification_runs if bool(dict(item).get("passed")))
        verification_fail_count = max(0, len(verification_runs) - verification_pass_count)
        recovery_actions = list(report_contract.get("recovery_actions") or [])
        remaining_blockers = list(report_contract.get("remaining_blockers") or [])
        best_next_step = str(report_contract.get("best_next_step") or "").strip()
        source_repo_changed = _snapshot_changed(source_snapshot_before, source_snapshot_after)
        live_source_repo_changed = _snapshot_changed(live_source_snapshot_before, live_source_snapshot_after)
        result_record = dict(result.get("record", {}) or {})
        validity = str(result_record.get("validity") or "valid")
        invalid_reason = str(result_record.get("invalid_reason") or "")
        if source_repo_changed:
            validity = "invalid_environment"
            invalid_reason = "source_repo_changed_during_isolated_run"

        metrics = {
            "validity": validity,
            "invalid_reason": invalid_reason,
            "success": bool(report_contract.get("productive_progress")),
            "report_contract_success": bool(report_contract.get("report_contract_success")),
            "productive_progress": bool(report_contract.get("productive_progress")),
            "actionable_no_progress": bool(report_contract.get("actionable_no_progress")),
            "follow_up_prompts": int(result.get("record", {}).get("follow_up_prompts") or 0),
            "commit_count": len(commits),
            "commit_shas_created": commits,
            "verification_pass_count": verification_pass_count,
            "verification_fail_count": verification_fail_count,
            "files_cleaned": max(
                0,
                int(initial_snapshot.get("dirty_file_count") or 0)
                - int(final_snapshot.get("dirty_file_count") or 0),
            ),
            "dirty_lines_drained": max(
                0,
                int(initial_snapshot.get("dirty_line_total") or 0)
                - int(final_snapshot.get("dirty_line_total") or 0),
            ),
            "time_to_first_real_progress": timeline_metrics.get("time_to_first_real_progress"),
            "time_to_first_commit": timeline_metrics.get("time_to_first_commit"),
            "stall_count": int(timeline_metrics.get("stall_count") or 0),
            "longest_stall_seconds": float(timeline_metrics.get("longest_stall_seconds") or 0.0),
            "recovery_count": len(recovery_actions),
            "guardrail_violation_count": int(report_payload.get("guardrail_violation_count") or 0),
            "protected_file_attempt_count": int(report_payload.get("protected_file_attempt_count") or 0),
            "tool_call_count": int(result.get("detailed_row", {}).get("run", {}).get("tool_calls") or 0),
            "tool_success_rate": None,
            "token_usage": dict(result.get("detailed_row", {}).get("run", {}).get("usage") or {}),
            "final_dirty_state": {
                "dirty_file_count": int(final_snapshot.get("dirty_file_count") or 0),
                "dirty_line_total": int(final_snapshot.get("dirty_line_total") or 0),
                "dirty_paths_sample": list(final_snapshot.get("dirty_paths") or [])[:25],
            },
            "remaining_blocker_count": len(remaining_blockers),
            "remaining_blockers": remaining_blockers,
            "best_next_step": best_next_step,
            "report_path": report_relpath,
            "artifact_success": bool(result.get("record", {}).get("artifact_success")),
            "response_confirmed": bool(result.get("record", {}).get("response_confirmed")),
            "timed_out": bool(result.get("record", {}).get("timed_out")),
            "runaway_guarded": bool(result.get("record", {}).get("runaway_guarded")),
            "runner_error_present": bool(result.get("record", {}).get("runner_error_present")),
            "source_repo_changed": source_repo_changed,
            "live_source_repo_changed": live_source_repo_changed,
        }
        competitor_rows[track_name] = metrics
        detailed_rows.append(
            {
                "track": track_name,
                "workspace_root": str(track_workspace),
                "rung": dict(rung),
                "source_snapshot_root": str(source_snapshot_root),
                "source_snapshot_before": source_snapshot_before,
                "source_snapshot_after": source_snapshot_after,
                "live_source_snapshot_before": live_source_snapshot_before,
                "live_source_snapshot_after": live_source_snapshot_after,
                "initial_snapshot": initial_snapshot,
                "final_snapshot": final_snapshot,
                "timeline": timeline,
                "report_payload": report_payload,
                "record": result.get("record"),
                "detailed_row": result.get("detailed_row"),
                "metrics": metrics,
            }
        )
        transcript_blobs[str(result["transcript_rel"])] = str(result["transcript_body"])

    summary = build_endurance_summary(
        run_id=run_id,
        task_pack=task_pack,
        rung=rung,
        competitor_rows=competitor_rows,
    )
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "benchmark_results.raw.json").write_text(
        json.dumps(detailed_rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "report.md").write_text(build_endurance_report(summary), encoding="utf-8")
    for rel, body in transcript_blobs.items():
        target = run_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return run_dir
