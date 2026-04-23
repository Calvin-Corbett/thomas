from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

from thomas.demo.agentic_benchmark import _run_task_track_entry


def _args(**overrides):
    values = {
        "thomas_runner": "embedded",
        "thomas_api_base": "https://thomas.local",
        "thomas_api_token": "",
        "task_timeout_seconds": 0.0,
    }
    values.update(overrides)
    return type("Args", (), values)()


def _track(**overrides):
    values = {
        "name": "baseline_raw",
        "kind": "raw",
        "profile": "local",
        "mode": "auto",
        "token_economy": "optimal",
        "max_iterations": None,
    }
    values.update(overrides)
    return type("Track", (), values)()


def test_run_task_track_entry_endurance_follow_up_recovers_missing_report_artifact(tmp_path: Path) -> None:
    artifact_root_rel = Path("runtime/agentic_bench/test-run")
    report_rel = "runtime/agentic_bench/test-run/thomas_os/endurance_report.json"
    task = {
        "id": "endurance_10m",
        "title": "Endurance rung endurance_10m",
        "prompt": (
            "Write the endurance report.\n\n"
            "Before finishing, write a JSON report to this exact relative path:\n"
            f"- {report_rel}\n\n"
            f"In your final response, mention: {report_rel}\n"
        ),
        "job_type": "coding",
        "success": {
            "response_contains": [report_rel],
            "required_files": [report_rel],
            "required_file_contains": {report_rel: '"commit_shas_created"'},
        },
    }
    prompts: list[str] = []

    async def _fake_embedded_task(_config, **kwargs):
        prompts.append(str(kwargs.get("prompt") or ""))
        if len(prompts) == 1:
            return {
                "ok": True,
                "text": "I am inspecting the repo first.",
                "error": "",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                "tool_calls": 1,
                "elapsed_seconds": 1.0,
            }
        target = tmp_path / report_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"commit_shas_created": []}\n', encoding="utf-8")
        return {
            "ok": True,
            "text": f"Wrote {report_rel}",
            "error": "",
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            "tool_calls": 1,
            "elapsed_seconds": 0.5,
        }

    with patch("thomas.demo.agentic_benchmark._run_thomas_embedded_task", new=_fake_embedded_task):
        row = asyncio.run(
            _run_task_track_entry(
                task_pack={"id": "pack", "type": "endurance_ladder", "competitor_requirements": {}},
                task=task,
                track=_track(name="thomas_os", kind="thomas", mode="thinking", token_economy="max"),
                args=_args(task_timeout_seconds=None),
                config=None,
                run_id="test-run",
                artifact_root_rel=artifact_root_rel,
                workspace_root=tmp_path,
                quality_min=1,
                quality_max=5,
                watch=False,
            )
        )

    assert row["record"]["success"] is True
    assert row["record"]["follow_up_prompts"] == 1
    assert len(prompts) == 2
    assert "Follow-up: the previous attempt is incomplete." in prompts[1]


def test_run_task_track_entry_marks_timeout_when_runner_exceeds_budget(tmp_path: Path) -> None:
    task = {
        "id": "task-timeout",
        "title": "Timeout Task",
        "prompt": "Do work.",
        "time_budget_seconds": 0.01,
        "success": {"response_contains": ["done"]},
    }

    async def _slow_raw_task(*args, **kwargs):
        await asyncio.sleep(0.05)
        return {
            "ok": True,
            "text": "done",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "tool_calls": 0,
            "elapsed_seconds": 0.05,
        }

    with patch("thomas.demo.agentic_benchmark._run_raw_task", new=_slow_raw_task):
        row = asyncio.run(
            _run_task_track_entry(
                task_pack={"id": "pack", "competitor_requirements": {}},
                task=task,
                track=_track(),
                args=_args(),
                config=None,
                run_id="test-run",
                artifact_root_rel=Path("runtime/agentic_bench/test-run"),
                workspace_root=tmp_path,
                quality_min=1,
                quality_max=5,
                watch=False,
            )
        )

    assert row["record"]["success"] is False
    assert "time budget" in row["record"]["notes"]
    assert row["record"]["timed_out"] is True


def test_run_task_track_entry_counts_artifact_success_without_confirmation(tmp_path: Path) -> None:
    artifact_root_rel = Path("runtime/agentic_bench/test-run")
    task = {
        "id": "task-artifact",
        "title": "Artifact Task",
        "prompt": "Write {{artifact_dir}}/artifact.txt and confirm it was written.",
        "success": {
            "response_contains": ["artifact.txt"],
            "required_files": ["{{artifact_dir}}/artifact.txt"],
        },
    }

    async def _fake_raw_task(*args, **kwargs):
        target = tmp_path / artifact_root_rel / "baseline_raw" / "artifact.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("ok", encoding="utf-8")
        return {
            "ok": False,
            "text": "",
            "error": "Task exceeded time budget of 60 seconds.",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "tool_calls": 0,
            "elapsed_seconds": 60.0,
        }

    with patch("thomas.demo.agentic_benchmark._run_raw_task", new=_fake_raw_task):
        row = asyncio.run(
            _run_task_track_entry(
                task_pack={"id": "pack", "competitor_requirements": {}},
                task=task,
                track=_track(),
                args=_args(),
                config=None,
                run_id="test-run",
                artifact_root_rel=artifact_root_rel,
                workspace_root=tmp_path,
                quality_min=1,
                quality_max=5,
                watch=False,
            )
        )

    assert row["record"]["success"] is True
    assert row["record"]["artifact_success"] is True
    assert row["record"]["response_confirmed"] is False


def test_run_task_track_entry_sends_benchmark_job_type_to_thomas_runner(tmp_path: Path) -> None:
    task = {
        "id": "task-bench",
        "title": "Benchmark Task",
        "prompt": "Read a file and report.",
        "success": {},
    }

    async def _fake_embedded_task(_config, **kwargs):
        assert kwargs["job_type"] == "benchmark"
        return {
            "ok": True,
            "text": "done",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "tool_calls": 0,
            "elapsed_seconds": 0.1,
        }

    with patch("thomas.demo.agentic_benchmark._run_thomas_embedded_task", new=_fake_embedded_task):
        row = asyncio.run(
            _run_task_track_entry(
                task_pack={"id": "pack", "competitor_requirements": {}},
                task=task,
                track=_track(name="thomas_os", kind="thomas", profile="codex"),
                args=_args(),
                config=None,
                run_id="test-run",
                artifact_root_rel=Path("runtime/agentic_bench/test-run"),
                workspace_root=tmp_path,
                quality_min=1,
                quality_max=5,
                watch=False,
            )
        )

    assert row["record"]["competitor"] == "thomas_os"
