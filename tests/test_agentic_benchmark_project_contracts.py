from __future__ import annotations

import asyncio
import json
import subprocess
import types
from pathlib import Path

from thomas.demo.agentic_benchmark_project import load_project_pack, run_project_benchmark

ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = ROOT / "benchmarks" / "packs" / "project" / "thomas_project_build_quality_todo_summary_v1.json"


def test_run_project_benchmark_accepts_string_verification_runs(tmp_path: Path) -> None:
    pack = load_project_pack(PACK_PATH)
    args = types.SimpleNamespace(
        thomas_runner="embedded",
        thomas_api_base="http://127.0.0.1:8899",
        thomas_api_token="",
        watch=False,
    )
    config = types.SimpleNamespace(tools=types.SimpleNamespace(sandbox_root=str(tmp_path)))
    track = types.SimpleNamespace(name="baseline_agent", kind="baseline_agent", profile="local")

    async def fake_run_task_entry(
        *,
        task_pack,
        task,
        track,
        args,
        config,
        run_id,
        artifact_root_rel,
        workspace_root,
        quality_min,
        quality_max,
        watch,
    ):
        _ = (task_pack, task, track, args, config, quality_min, quality_max, watch)
        report_path = workspace_root / artifact_root_rel / "baseline_agent" / "project_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        task_file = workspace_root / "todo_service" / "tasks.py"
        task_file.write_text(task_file.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(workspace_root), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(workspace_root), "commit", "-m", "Implement feature"], check=True)
        head = subprocess.run(
            ["git", "-C", str(workspace_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
        report_path.write_text(
            json.dumps(
                {
                    "commit_shas_created": [head],
                    "verification_runs": ["python -m pytest checks/priority_summary_check.py -q (passed: 4 tests)"],
                    "changed_files": ["todo_service/tasks.py", "checks/priority_summary_check.py"],
                    "feature_summary": "Implemented summary feature.",
                    "remaining_blockers": [],
                    "best_next_step": "None.",
                }
            ),
            encoding="utf-8",
        )
        return {
            "record": {
                "validity": "valid",
                "invalid_reason": "",
                "success": True,
                "artifact_success": True,
                "response_confirmed": True,
                "timed_out": False,
                "runner_error_present": False,
                "follow_up_prompts": 0,
                "elapsed_seconds": 12.5,
            },
            "detailed_row": {
                "run": {
                    "tool_calls": 3,
                    "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                }
            },
            "transcript_rel": "transcripts/baseline_agent/todo_priority_summary.md",
            "transcript_body": "done",
        }

    run_dir = asyncio.run(
        run_project_benchmark(
            args=args,
            config=config,
            task_pack=pack,
            tracks=[track],
            run_id="project-pack-string-verification",
            workspace_root=tmp_path,
            runs_dir=tmp_path / "runs",
            quality_min=1,
            quality_max=5,
            run_task_entry=fake_run_task_entry,
        )
    )

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    metrics = summary["competitors"]["baseline_agent"]
    assert metrics["success_count"] == 1
    assert metrics["verification_pass_count"] == 1


def test_run_project_benchmark_accepts_short_commit_shas(tmp_path: Path) -> None:
    pack = load_project_pack(PACK_PATH)
    args = types.SimpleNamespace(
        thomas_runner="embedded",
        thomas_api_base="http://127.0.0.1:8899",
        thomas_api_token="",
        watch=False,
    )
    config = types.SimpleNamespace(tools=types.SimpleNamespace(sandbox_root=str(tmp_path)))
    track = types.SimpleNamespace(name="baseline_agent", kind="baseline_agent", profile="local")

    async def fake_run_task_entry(
        *,
        task_pack,
        task,
        track,
        args,
        config,
        run_id,
        artifact_root_rel,
        workspace_root,
        quality_min,
        quality_max,
        watch,
    ):
        _ = (task_pack, task, track, args, config, quality_min, quality_max, watch)
        report_path = workspace_root / artifact_root_rel / "baseline_agent" / "project_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        task_file = workspace_root / "todo_service" / "tasks.py"
        task_file.write_text(task_file.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(workspace_root), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(workspace_root), "commit", "-m", "Implement feature"], check=True)
        head = subprocess.run(
            ["git", "-C", str(workspace_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
        report_path.write_text(
            json.dumps(
                {
                    "commit_shas_created": [head[:7]],
                    "verification_runs": [
                        {"command": "python -m pytest checks/priority_summary_check.py -q", "passed": True}
                    ],
                    "changed_files": ["todo_service/tasks.py"],
                    "feature_summary": "Implemented summary feature.",
                    "remaining_blockers": [],
                    "best_next_step": "None.",
                }
            ),
            encoding="utf-8",
        )
        return {
            "record": {
                "validity": "valid",
                "invalid_reason": "",
                "success": True,
                "artifact_success": True,
                "response_confirmed": True,
                "timed_out": False,
                "runner_error_present": False,
                "follow_up_prompts": 0,
                "elapsed_seconds": 12.5,
            },
            "detailed_row": {
                "run": {
                    "tool_calls": 3,
                    "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                }
            },
            "transcript_rel": "transcripts/baseline_agent/todo_priority_summary.md",
            "transcript_body": "done",
        }

    run_dir = asyncio.run(
        run_project_benchmark(
            args=args,
            config=config,
            task_pack=pack,
            tracks=[track],
            run_id="project-pack-short-sha",
            workspace_root=tmp_path,
            runs_dir=tmp_path / "runs",
            quality_min=1,
            quality_max=5,
            run_task_entry=fake_run_task_entry,
        )
    )

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    metrics = summary["competitors"]["baseline_agent"]
    assert metrics["success_count"] == 1
