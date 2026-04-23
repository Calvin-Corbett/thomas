from __future__ import annotations

import argparse
import copy
import json
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from thomas.core.benchmark_lane import (
    BENCHMARK_REPO_ROOT_ENV,
    BENCHMARK_SINGLE_AGENT_ENV,
    BENCHMARK_WORKBOARD_PATH_ENV,
)
from thomas.demo.agentic_benchmark_core import render_task
from thomas.demo.agentic_benchmark_endurance_runtime import (
    copy_workspace_snapshot,
    isolated_thomas_server,
    new_commits,
)
from thomas.demo.agentic_benchmark_project_contract import (
    evaluate_project_report_contract,
    read_project_report,
)
from thomas.demo.agentic_benchmark_project_pack import (
    git_in_workspace,
    load_project_pack,
    prepare_project_workspace,
    resolve_task_fixture_root,
    snapshot_tree,
)
from thomas.demo.agentic_benchmark_project_report import build_project_report_markdown

__all__ = ["load_project_pack", "run_project_benchmark"]


@contextmanager
def _temporary_project_env(*, home_dir: Path, workspace_root: Path, run_id: str, track_name: str):
    env_values = {
        "THOMAS_DATA_DIR": str(home_dir),
        "THOMAS_HOME": str(home_dir),
        "THOMAS_STATE_DIR": str(home_dir),
        "THOMAS_RUNTIME_DIR": str(home_dir / "runtime"),
        "THOMAS_ARTIFACT_DIR": str(home_dir / "artifacts"),
        "THOMAS_ARTIFACTS_DIR": str(home_dir / "artifacts"),
        "THOMAS_TASK_MANAGER_LOOP_ENABLED": "0",
        BENCHMARK_SINGLE_AGENT_ENV: "1",
        "THOMAS_BENCHMARK_ALLOW_CODING_PIPELINE": "1",
        BENCHMARK_REPO_ROOT_ENV: str(workspace_root),
        BENCHMARK_WORKBOARD_PATH_ENV: str(workspace_root / "WORKBOARD.md"),
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


@contextmanager
def _temporary_cwd(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def run_project_benchmark(
    *,
    args: argparse.Namespace,
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
    del workspace_root
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    artifact_root_rel = Path("runtime") / "agentic_bench" / run_id

    competitor_rows: dict[str, list[dict[str, Any]]] = {str(track.name): [] for track in tracks}
    detailed_rows: list[dict[str, Any]] = []
    transcript_blobs: dict[str, str] = {}

    for task in list(task_pack.get("tasks") or []):
        task_id = str(task.get("id") or "").strip()
        fixture_root = resolve_task_fixture_root(task_pack, task)
        if not fixture_root.exists():
            raise FileNotFoundError(f"Project benchmark fixture does not exist: {fixture_root}")
        source_snapshot_root = run_dir / "source-snapshots" / task_id
        copy_workspace_snapshot(fixture_root, source_snapshot_root)
        source_snapshot_before = snapshot_tree(source_snapshot_root)
        live_fixture_before = snapshot_tree(fixture_root)
        for track in tracks:
            track_name = str(track.name)
            track_workspace = run_dir / "workspaces" / task_id / track_name
            prepare_project_workspace(source_snapshot_root, track_workspace)
            benchmark_home = run_dir / "track-state" / task_id / track_name
            benchmark_home.mkdir(parents=True, exist_ok=True)

            track_config = copy.deepcopy(config)
            if hasattr(track_config, "tools"):
                track_config.tools.sandbox_root = str(track_workspace)

            initial_head = git_in_workspace(track_workspace, "rev-parse", "HEAD").stdout.strip()
            context = {
                "run_id": run_id,
                "track": track_name,
                "artifact_dir": str((artifact_root_rel / track_name).as_posix()),
                "workspace": str(track_workspace.as_posix()),
            }
            rendered_task = render_task(task, context)
            required_files = list((rendered_task.get("success") or {}).get("required_files") or [])
            report_rel = str(required_files[0] or "").strip() if required_files else ""
            report_path = track_workspace / Path(report_rel) if report_rel else None

            active_args = copy.copy(args)
            with (
                _temporary_project_env(
                    home_dir=benchmark_home,
                    workspace_root=track_workspace,
                    run_id=run_id,
                    track_name=track_name,
                ),
                _temporary_cwd(track_workspace),
            ):
                if str(track.kind or "") == "thomas" and str(args.thomas_runner or "") == "api":
                    env = {
                        "THOMAS_TASK_MANAGER_LOOP_ENABLED": "0",
                        BENCHMARK_SINGLE_AGENT_ENV: "1",
                        "THOMAS_BENCHMARK_ALLOW_CODING_PIPELINE": "1",
                        BENCHMARK_REPO_ROOT_ENV: str(track_workspace),
                        BENCHMARK_WORKBOARD_PATH_ENV: str(track_workspace / "WORKBOARD.md"),
                        "THOMAS_BENCHMARK_RUN_ID": run_id,
                        "THOMAS_BENCHMARK_TRACK": track_name,
                    }
                    with isolated_thomas_server(track_workspace, benchmark_home, extra_env=env) as base_url:
                        active_args.thomas_api_base = base_url
                        result = await run_task_entry(
                            task_pack=task_pack,
                            task=task,
                            track=track,
                            args=active_args,
                            config=track_config,
                            run_id=run_id,
                            artifact_root_rel=artifact_root_rel,
                            workspace_root=track_workspace,
                            quality_min=quality_min,
                            quality_max=quality_max,
                            watch=bool(getattr(args, "watch", False)),
                        )
                else:
                    result = await run_task_entry(
                        task_pack=task_pack,
                        task=task,
                        track=track,
                        args=active_args,
                        config=track_config,
                        run_id=run_id,
                        artifact_root_rel=artifact_root_rel,
                        workspace_root=track_workspace,
                        quality_min=quality_min,
                        quality_max=quality_max,
                        watch=bool(getattr(args, "watch", False)),
                    )

            commits = new_commits(track_workspace, initial_head)
            report_payload = read_project_report(report_path) if report_path is not None else {}
            project_contract = evaluate_project_report_contract(report_payload, commits)
            record = dict(result.get("record", {}) or {})
            detailed = dict(result.get("detailed_row", {}) or {})

            source_snapshot_after = snapshot_tree(source_snapshot_root)
            live_fixture_after = snapshot_tree(fixture_root)
            source_snapshot_changed = source_snapshot_before != source_snapshot_after
            live_fixture_changed = live_fixture_before != live_fixture_after
            validity = str(record.get("validity") or "valid")
            invalid_reason = str(record.get("invalid_reason") or "")
            if source_snapshot_changed:
                validity = "invalid_environment"
                invalid_reason = "project_source_snapshot_changed_during_run"
            elif live_fixture_changed:
                validity = "invalid_environment"
                invalid_reason = "project_live_fixture_changed_during_run"

            metrics = {
                "task_id": task_id,
                "competitor": track_name,
                "validity": validity,
                "invalid_reason": invalid_reason,
                "success": validity == "valid" and bool(record.get("success")) and bool(project_contract.get("report_contract_success")) and bool(project_contract.get("commit_shas_created")) and int(project_contract.get("verification_pass_count") or 0) > 0,
                "report_contract_success": bool(project_contract.get("report_contract_success")),
                "artifact_success": bool(record.get("artifact_success")),
                "response_confirmed": bool(record.get("response_confirmed")),
                "timed_out": bool(record.get("timed_out")),
                "runner_error_present": bool(record.get("runner_error_present")),
                "follow_up_prompts": int(record.get("follow_up_prompts") or 0),
                "elapsed_seconds": float(record.get("elapsed_seconds") or 0.0),
                "tool_call_count": int((detailed.get("run") or {}).get("tool_calls") or 0),
                "token_usage": dict((detailed.get("run") or {}).get("usage") or {}),
                "commit_count": len(project_contract.get("commit_shas_created") or []),
                "commit_shas_created": list(project_contract.get("commit_shas_created") or []),
                "verification_pass_count": int(project_contract.get("verification_pass_count") or 0),
                "verification_fail_count": int(project_contract.get("verification_fail_count") or 0),
                "changed_file_count": int(project_contract.get("changed_file_count") or 0),
                "changed_files": list(project_contract.get("changed_files") or []),
                "remaining_blocker_count": int(project_contract.get("remaining_blocker_count") or 0),
                "remaining_blockers": list(project_contract.get("remaining_blockers") or []),
                "best_next_step": str(project_contract.get("best_next_step") or ""),
                "feature_summary": str(project_contract.get("feature_summary") or ""),
                "source_snapshot_changed": source_snapshot_changed,
                "live_fixture_changed": live_fixture_changed,
            }
            competitor_rows[track_name].append(metrics)
            detailed_rows.append(
                {
                    "task_id": task_id,
                    "track": track_name,
                    "record": record,
                    "detailed_row": detailed,
                    "project_contract": project_contract,
                    "workspace": str(track_workspace),
                }
            )
            transcript_blobs[str(result["transcript_rel"])] = str(result["transcript_body"])

    summary: dict[str, Any] = {
        "run_id": run_id,
        "pack_id": str(task_pack.get("id") or ""),
        "pack_type": "project",
        "family": str(task_pack.get("family") or ""),
        "competitors": {},
    }
    for track_name, rows in competitor_rows.items():
        total = max(1, len(rows))
        token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        for row in rows:
            usage = dict(row.get("token_usage") or {})
            for key in token_usage:
                token_usage[key] += int(usage.get(key, 0) or 0)
        summary["competitors"][track_name] = {
            "validity": "valid"
            if all(str(row.get("validity") or "valid") == "valid" for row in rows)
            else "invalid_environment",
            "task_count": len(rows),
            "success_count": sum(1 for row in rows if bool(row.get("success"))),
            "success_rate": round(sum(1 for row in rows if bool(row.get("success"))) / total, 3),
            "report_contract_success_count": sum(1 for row in rows if bool(row.get("report_contract_success"))),
            "artifact_success_count": sum(1 for row in rows if bool(row.get("artifact_success"))),
            "response_confirmed_count": sum(1 for row in rows if bool(row.get("response_confirmed"))),
            "timeout_count": sum(1 for row in rows if bool(row.get("timed_out"))),
            "runner_error_count": sum(1 for row in rows if bool(row.get("runner_error_present"))),
            "follow_up_prompt_count": sum(int(row.get("follow_up_prompts") or 0) for row in rows),
            "commit_count": sum(int(row.get("commit_count") or 0) for row in rows),
            "verification_pass_count": sum(int(row.get("verification_pass_count") or 0) for row in rows),
            "verification_fail_count": sum(int(row.get("verification_fail_count") or 0) for row in rows),
            "changed_file_count": sum(int(row.get("changed_file_count") or 0) for row in rows),
            "remaining_blocker_count": sum(int(row.get("remaining_blocker_count") or 0) for row in rows),
            "avg_elapsed_seconds": round(sum(float(row.get("elapsed_seconds") or 0.0) for row in rows) / total, 3),
            "tool_call_count": sum(int(row.get("tool_call_count") or 0) for row in rows),
            "token_usage": token_usage,
            "commit_shas_created": [sha for row in rows for sha in list(row.get("commit_shas_created") or [])],
            "source_snapshot_changed": any(bool(row.get("source_snapshot_changed")) for row in rows),
            "live_fixture_changed": any(bool(row.get("live_fixture_changed")) for row in rows),
        }

    _write_json(run_dir / "summary.json", summary)
    _write_json(run_dir / "benchmark_results.raw.json", detailed_rows)
    _write_json(run_dir / "task_pack.agentic.snapshot.json", dict(task_pack))
    (run_dir / "report.md").write_text(
        build_project_report_markdown(run_id=run_id, task_pack=task_pack, summary=summary),
        encoding="utf-8",
    )
    for rel, body in transcript_blobs.items():
        target = run_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return run_dir
