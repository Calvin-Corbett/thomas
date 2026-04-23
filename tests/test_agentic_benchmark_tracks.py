from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

from thomas.demo.agentic_benchmark import (
    _build_baseline_track,
    _resolve_task_timeout_seconds,
    _run_task_track_entry,
    load_agentic_task_pack,
)


def _args(**overrides):
    values = {
        "thomas_runner": "embedded",
        "thomas_api_base": "https://thomas.local",
        "thomas_api_token": "",
        "baseline_runner": "auto",
        "baseline_name": "",
        "baseline_mode": "auto",
        "baseline_token_economy": "optimal",
        "baseline_max_iterations": None,
        "profile": "local",
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


def test_load_agentic_task_pack_preserves_benchmark_metadata(tmp_path: Path) -> None:
    pack_path = tmp_path / "pack.json"
    pack_path.write_text(
        json.dumps(
            {
                "id": "cap-pack",
                "name": "Capability Pack",
                "version": 2,
                "type": "capability",
                "family": "thomas_product_capability",
                "competitor_requirements": {"required_capability_class": "tool_using_agent"},
                "report_metrics": ["validity_rate", "success_rate"],
                "tasks": [{"id": "t1", "title": "T", "prompt": "P", "success": {}}],
            }
        ),
        encoding="utf-8",
    )

    pack = load_agentic_task_pack(pack_path)

    assert pack["type"] == "capability"
    assert pack["family"] == "thomas_product_capability"
    assert pack["competitor_requirements"]["required_capability_class"] == "tool_using_agent"
    assert pack["report_metrics"] == ["validity_rate", "success_rate"]


def test_build_baseline_track_auto_promotes_tool_pack_to_tool_agent() -> None:
    track = _build_baseline_track(
        {
            "id": "cap-pack",
            "competitor_requirements": {"required_capability_class": "tool_using_agent"},
        },
        _args(),
    )

    assert track.kind == "baseline_agent"
    assert track.name == "baseline_agent"


def test_build_baseline_track_auto_keeps_raw_for_text_only_pack() -> None:
    track = _build_baseline_track(
        {
            "id": "text-pack",
            "competitor_requirements": {"required_capability_class": "text_only"},
        },
        _args(),
    )

    assert track.kind == "raw"
    assert track.name == "baseline_raw"


def test_resolve_task_timeout_seconds_prefers_lower_positive_budget() -> None:
    timeout_seconds = _resolve_task_timeout_seconds({"time_budget_seconds": 240}, _args(task_timeout_seconds=30.0))

    assert timeout_seconds == 30.0


def test_run_task_track_entry_marks_invalid_text_only_lane_for_tool_pack(tmp_path: Path) -> None:
    artifact_root_rel = Path("runtime/agentic_bench/test-run")
    task = {
        "id": "task01",
        "title": "Task 01",
        "prompt": "Write {{artifact_dir}}/task01.json and confirm it was written.",
        "success": {"required_files": ["{{artifact_dir}}/task01.json"]},
    }

    async def _unexpected_raw_task(**kwargs):
        raise AssertionError("raw runner should not execute for an invalid competitor capability")

    with patch("thomas.demo.agentic_benchmark._run_raw_task", new=_unexpected_raw_task):
        row = asyncio.run(
            _run_task_track_entry(
                task_pack={
                    "id": "pack",
                    "competitor_requirements": {"required_capability_class": "tool_using_agent"},
                },
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

    assert row["record"]["success"] is False
    assert row["record"]["validity"] == "invalid_competitor_capability"
    assert "required capability" in row["record"]["invalid_reason"]


def test_run_task_track_entry_executes_tool_agent_lane_for_tool_pack(tmp_path: Path) -> None:
    artifact_root_rel = Path("runtime/agentic_bench/test-run")
    task = {
        "id": "task01",
        "title": "Task 01",
        "prompt": "Write {{artifact_dir}}/task01.json and confirm it was written.",
        "success": {"required_files": ["{{artifact_dir}}/task01.json"]},
    }

    async def _fake_tool_agent_task(_config, **kwargs):
        target = tmp_path / artifact_root_rel / "baseline_agent" / "task01.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}", encoding="utf-8")
        return {
            "ok": True,
            "text": "Wrote runtime/agentic_bench/test-run/baseline_agent/task01.json",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "tool_calls": 1,
            "elapsed_seconds": 0.5,
        }

    with patch("thomas.demo.agentic_benchmark._run_tool_agent_task", new=_fake_tool_agent_task):
        row = asyncio.run(
            _run_task_track_entry(
                task_pack={
                    "id": "pack",
                    "competitor_requirements": {"required_capability_class": "tool_using_agent"},
                },
                task=task,
                track=_track(name="baseline_agent", kind="baseline_agent"),
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
    assert row["record"]["validity"] == "valid"
    assert row["record"]["competitor"] == "baseline_agent"
