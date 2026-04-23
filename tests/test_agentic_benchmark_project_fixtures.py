from __future__ import annotations

import asyncio
import json
import subprocess
import types
from pathlib import Path

from thomas.demo.agentic_benchmark_project import load_project_pack, run_project_benchmark

ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = ROOT / "benchmarks" / "packs" / "project" / "thomas_project_build_quality_todo_summary_v1.json"


def test_run_project_benchmark_marks_live_fixture_mutation_invalid(tmp_path: Path) -> None:
    pack = load_project_pack(PACK_PATH)
    args = types.SimpleNamespace(
        thomas_runner="embedded",
        thomas_api_base="http://127.0.0.1:8899",
        thomas_api_token="",
        watch=False,
    )
    config = types.SimpleNamespace(tools=types.SimpleNamespace(sandbox_root=str(tmp_path)))
    track = types.SimpleNamespace(name="baseline_agent", kind="baseline_agent", profile="local")
    fixture_root = ROOT / pack["fixture_path"]
    original_text = (fixture_root / "todo_service" / "tasks.py").read_text(encoding="utf-8")

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
        _ = (
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
        )
        (fixture_root / "todo_service" / "tasks.py").write_text(
            original_text + "\n# live fixture mutation\n", encoding="utf-8"
        )
        return {
            "record": {
                "validity": "valid",
                "invalid_reason": "",
                "success": False,
                "artifact_success": False,
                "response_confirmed": False,
                "timed_out": False,
                "runner_error_present": False,
                "follow_up_prompts": 0,
                "elapsed_seconds": 1.0,
            },
            "detailed_row": {
                "run": {"tool_calls": 0, "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
            },
            "transcript_rel": "transcripts/baseline_agent/todo_priority_summary.md",
            "transcript_body": "done",
        }

    try:
        run_dir = asyncio.run(
            run_project_benchmark(
                args=args,
                config=config,
                task_pack=pack,
                tracks=[track],
                run_id="project-pack-fixture-leak",
                workspace_root=tmp_path,
                runs_dir=tmp_path / "runs",
                quality_min=1,
                quality_max=5,
                run_task_entry=fake_run_task_entry,
            )
        )
    finally:
        (fixture_root / "todo_service" / "tasks.py").write_text(original_text, encoding="utf-8")

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    metrics = summary["competitors"]["baseline_agent"]
    assert metrics["validity"] == "invalid_environment"
    assert metrics["live_fixture_changed"] is True


def test_run_project_benchmark_supports_task_level_fixture(tmp_path: Path) -> None:
    pack = dict(load_project_pack(PACK_PATH))
    fixture_root = tmp_path / "custom_fixture"
    (fixture_root / "todo_service").mkdir(parents=True)
    (fixture_root / "checks").mkdir()
    (fixture_root / "todo_service" / "__init__.py").write_text("", encoding="utf-8")
    (fixture_root / "todo_service" / "__main__.py").write_text(
        "from .cli import main\nraise SystemExit(main())\n", encoding="utf-8"
    )
    (fixture_root / "todo_service" / "tasks.py").write_text("VALUE = 'custom'\n", encoding="utf-8")
    (fixture_root / "todo_service" / "cli.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    (fixture_root / "checks" / "priority_summary_check.py").write_text(
        "def test_custom():\n    assert True\n", encoding="utf-8"
    )
    pack["tasks"] = [dict(list(pack["tasks"])[0], fixture_path=str(fixture_root))]

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
        assert (workspace_root / "todo_service" / "tasks.py").read_text(encoding="utf-8") == "VALUE = 'custom'\n"
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
                    "verification_runs": [
                        {"command": "python -m pytest checks/priority_summary_check.py -q", "passed": True}
                    ],
                    "changed_files": ["todo_service/tasks.py"],
                    "feature_summary": "Implemented custom feature.",
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
                "run": {"tool_calls": 3, "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}
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
            run_id="project-pack-task-fixture",
            workspace_root=tmp_path,
            runs_dir=tmp_path / "runs",
            quality_min=1,
            quality_max=5,
            run_task_entry=fake_run_task_entry,
        )
    )
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["competitors"]["baseline_agent"]["success_count"] == 1
