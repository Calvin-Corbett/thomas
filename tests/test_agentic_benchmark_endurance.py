import asyncio
import json
import os
import subprocess
import tempfile
import types
import unittest
from pathlib import Path

from thomas.demo.agentic_benchmark_endurance import (
    _snapshot_ignore,
    _temporary_benchmark_env,
    build_endurance_task,
    load_endurance_ladder_pack,
    run_endurance_ladder,
)


class TestAgenticBenchmarkEndurance(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp_path = Path(self._tmpdir.name)

    def _init_dirty_repo(self) -> Path:
        repo = self.tmp_path / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Benchmark Test"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "bench@example.com"], check=True)
        target = repo / "tracked.txt"
        target.write_text("one\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "initial"], check=True, capture_output=True, text=True)
        target.write_text("one\ntwo\n", encoding="utf-8")
        return repo

    def test_load_endurance_ladder_pack(self) -> None:
        pack_path = self.tmp_path / "endurance.json"
        pack_path.write_text(
            json.dumps(
                {
                    "id": "endurance-demo",
                    "type": "endurance_ladder",
                    "rungs": [{"id": "endurance_10m", "time_budget_minutes": 10}],
                }
            ),
            encoding="utf-8",
        )
        pack = load_endurance_ladder_pack(pack_path)
        self.assertEqual(pack["type"], "endurance_ladder")
        self.assertEqual(pack["rungs"][0]["id"], "endurance_10m")

    def test_build_endurance_task_mentions_report_path(self) -> None:
        task = build_endurance_task(
            rung={"id": "endurance_10m", "time_budget_minutes": 10},
            task_contract={
                "goal": "Drain the repo.",
                "rules": ["Use guarded commits only."],
                "required_final_output": ["commit_shas_created"],
            },
            report_relpath="runtime/agentic_bench/run-a/baseline_agent/endurance_report.json",
        )
        self.assertIn("Time budget: 10 minutes.", task["prompt"])
        self.assertIn("runtime/agentic_bench/run-a/baseline_agent/endurance_report.json", task["prompt"])
        self.assertEqual(task["time_budget_seconds"], 600)
        self.assertEqual(task["job_type"], "coding")

    def test_temporary_benchmark_env_sets_single_agent_isolation_vars(self) -> None:
        workspace = self.tmp_path / "workspace"
        (workspace / "plans" / "thomas").mkdir(parents=True, exist_ok=True)
        (workspace / "plans" / "thomas" / "WORKBOARD.md").write_text("# Thomas Workboard\n", encoding="utf-8")
        home = self.tmp_path / "home"
        with _temporary_benchmark_env(
            home_dir=home,
            workspace_root=workspace,
            run_id="run-1",
            track_name="thomas_os",
        ):
            self.assertEqual(os.environ["THOMAS_TASK_MANAGER_LOOP_ENABLED"], "0")
            self.assertEqual(os.environ["THOMAS_BENCHMARK_SINGLE_AGENT"], "1")
            self.assertEqual(os.environ["THOMAS_BENCHMARK_REPO_ROOT"], str(workspace))
            self.assertEqual(
                os.environ["THOMAS_BENCHMARK_WORKBOARD_PATH"],
                str(workspace / "plans" / "thomas" / "WORKBOARD.md"),
            )

    def test_snapshot_ignore_skips_generated_caches_and_benchmark_artifacts(self) -> None:
        repo = self.tmp_path / "repo"
        current_dir = repo / "apps" / "site"
        current_dir.mkdir(parents=True, exist_ok=True)
        ignored = _snapshot_ignore(
            repo,
            str(current_dir),
            [".next", "node_modules", "src", "tmp"],
        )
        self.assertIn(".next", ignored)
        self.assertIn("node_modules", ignored)
        self.assertIn("tmp", ignored)
        self.assertNotIn("src", ignored)

        runtime_dir = repo / "demo"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        ignored_runtime = _snapshot_ignore(repo, str(runtime_dir), ["agentic-runs", "docs"])
        self.assertIn("agentic-runs", ignored_runtime)
        self.assertNotIn("docs", ignored_runtime)

        root_runtime = _snapshot_ignore(repo, str(repo), ["runtime", "src"])
        self.assertIn("runtime", root_runtime)
        self.assertNotIn("src", root_runtime)

    def test_run_endurance_ladder_writes_git_metrics(self) -> None:
        repo = self._init_dirty_repo()
        pack = {
            "id": "endurance-demo",
            "version": 1,
            "type": "endurance_ladder",
            "task_contract": {
                "goal": "Drain the repo.",
                "rules": ["Use guarded commits only."],
                "required_final_output": ["commit_shas_created"],
            },
            "rungs": [{"id": "endurance_10m", "time_budget_minutes": 10}],
            "competitor_requirements": {"required_capability_class": "tool_using_agent"},
        }
        args = types.SimpleNamespace(
            endurance_rung="endurance_10m",
            endurance_poll_seconds=1.0,
            watch=False,
        )
        config = types.SimpleNamespace(tools=types.SimpleNamespace(sandbox_root=str(repo)))
        track = types.SimpleNamespace(name="baseline_agent")

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
            report_path = workspace_root / artifact_root_rel / track.name / "endurance_report.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            tracked = workspace_root / "tracked.txt"
            tracked.write_text("one\ntwo\nthree\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(workspace_root), "add", "tracked.txt"], check=True)
            subprocess.run(
                ["git", "-C", str(workspace_root), "commit", "-m", "bench progress"],
                check=True,
                capture_output=True,
                text=True,
            )
            report_path.write_text(
                json.dumps(
                    {
                        "commit_shas_created": [],
                        "verification_runs": [{"command": "pytest -q", "passed": True}],
                        "remaining_blockers": ["next blocker"],
                        "best_next_step": "keep going",
                        "recovery_actions": ["split a file"],
                        "guardrail_violation_count": 0,
                        "protected_file_attempt_count": 0,
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
                    "runaway_guarded": False,
                    "runner_error_present": False,
                },
                "detailed_row": {
                    "run": {
                        "tool_calls": 2,
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                    }
                },
                "transcript_rel": "transcripts/baseline_agent/endurance.md",
                "transcript_body": "done",
            }

        run_dir = asyncio.run(
            run_endurance_ladder(
                args=args,
                config=config,
                task_pack=pack,
                tracks=[track],
                run_id="endurance-test",
                workspace_root=repo,
                runs_dir=self.tmp_path / "runs",
                quality_min=1,
                quality_max=5,
                run_task_entry=fake_run_task_entry,
            )
        )
        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        metrics = summary["competitors"]["baseline_agent"]
        self.assertTrue(metrics["report_contract_success"])
        self.assertTrue(metrics["productive_progress"])
        self.assertTrue(metrics["success"])
        self.assertFalse(metrics["actionable_no_progress"])
        self.assertEqual(metrics["commit_count"], 1)
        self.assertEqual(metrics["verification_pass_count"], 1)
        self.assertEqual(metrics["remaining_blocker_count"], 1)
        self.assertEqual(metrics["tool_call_count"], 2)
        self.assertEqual(metrics["final_dirty_state"]["dirty_file_count"], 0)
        self.assertFalse(metrics["source_repo_changed"])

    def test_run_endurance_ladder_keeps_embedded_runner_when_requested(self) -> None:
        repo = self._init_dirty_repo()
        pack = {
            "id": "endurance-demo",
            "version": 1,
            "type": "endurance_ladder",
            "task_contract": {
                "goal": "Drain the repo.",
                "rules": ["Use guarded commits only."],
                "required_final_output": ["commit_shas_created"],
            },
            "rungs": [{"id": "endurance_10m", "time_budget_minutes": 10}],
            "competitor_requirements": {"required_capability_class": "tool_using_agent"},
        }
        args = types.SimpleNamespace(
            endurance_rung="endurance_10m",
            endurance_poll_seconds=1.0,
            watch=False,
            thomas_runner="embedded",
            thomas_api_base="https://thomas.local",
            thomas_api_token="",
        )
        config = types.SimpleNamespace(tools=types.SimpleNamespace(sandbox_root=str(repo)))
        track = types.SimpleNamespace(name="thomas_os", kind="thomas")
        seen_runner: list[str] = []

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
            _ = (task_pack, task, track, config, run_id, quality_min, quality_max, watch)
            seen_runner.append(str(args.thomas_runner))
            report_path = workspace_root / artifact_root_rel / "thomas_os" / "endurance_report.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(
                    {
                        "commit_shas_created": [],
                        "verification_runs": [],
                        "remaining_blockers": ["blocked"],
                        "best_next_step": "resume later",
                        "recovery_actions": [],
                        "guardrail_violation_count": 0,
                        "protected_file_attempt_count": 0,
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
                    "runaway_guarded": False,
                    "runner_error_present": False,
                },
                "detailed_row": {"run": {"tool_calls": 0, "usage": {}}},
                "transcript_rel": "transcripts/thomas_os/endurance.md",
                "transcript_body": "done",
            }

        asyncio.run(
            run_endurance_ladder(
                args=args,
                config=config,
                task_pack=pack,
                tracks=[track],
                run_id="endurance-embedded-runner",
                workspace_root=repo,
                runs_dir=self.tmp_path / "runs",
                quality_min=1,
                quality_max=5,
                run_task_entry=fake_run_task_entry,
            )
        )

        self.assertEqual(seen_runner, ["embedded"])

    def test_run_endurance_ladder_marks_report_only_run_as_no_progress(self) -> None:
        repo = self._init_dirty_repo()
        pack = {
            "id": "endurance-demo",
            "version": 1,
            "type": "endurance_ladder",
            "task_contract": {
                "goal": "Drain the repo.",
                "rules": ["Use guarded commits only."],
                "required_final_output": ["commit_shas_created"],
            },
            "rungs": [{"id": "endurance_10m", "time_budget_minutes": 10}],
            "competitor_requirements": {"required_capability_class": "tool_using_agent"},
        }
        args = types.SimpleNamespace(
            endurance_rung="endurance_10m",
            endurance_poll_seconds=1.0,
            watch=False,
        )
        config = types.SimpleNamespace(tools=types.SimpleNamespace(sandbox_root=str(repo)))
        track = types.SimpleNamespace(name="baseline_agent")

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
            _ = (task_pack, task, track, args, config, run_id, quality_min, quality_max, watch)
            report_path = workspace_root / artifact_root_rel / "baseline_agent" / "endurance_report.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(
                    {
                        "commit_shas_created": [],
                        "verification_runs": [],
                        "remaining_blockers": ["monolith guard blocked the next slice"],
                        "best_next_step": "split the oversized file and retry the guarded commit",
                        "recovery_actions": ["captured blockers in this report"],
                        "guardrail_violation_count": 0,
                        "protected_file_attempt_count": 0,
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
                    "runaway_guarded": False,
                    "runner_error_present": False,
                },
                "detailed_row": {"run": {"tool_calls": 1, "usage": {"total_tokens": 25}}},
                "transcript_rel": "transcripts/baseline_agent/endurance.md",
                "transcript_body": "done",
            }

        run_dir = asyncio.run(
            run_endurance_ladder(
                args=args,
                config=config,
                task_pack=pack,
                tracks=[track],
                run_id="endurance-no-progress",
                workspace_root=repo,
                runs_dir=self.tmp_path / "runs",
                quality_min=1,
                quality_max=5,
                run_task_entry=fake_run_task_entry,
            )
        )

        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        metrics = summary["competitors"]["baseline_agent"]
        self.assertTrue(metrics["report_contract_success"])
        self.assertFalse(metrics["productive_progress"])
        self.assertTrue(metrics["actionable_no_progress"])
        self.assertFalse(metrics["success"])
        self.assertEqual(metrics["commit_count"], 0)

    def test_run_endurance_ladder_ignores_live_repo_changes_when_snapshot_stays_clean(self) -> None:
        repo = self._init_dirty_repo()
        pack = {
            "id": "endurance-demo",
            "version": 1,
            "type": "endurance_ladder",
            "task_contract": {
                "goal": "Drain the repo.",
                "rules": ["Use guarded commits only."],
                "required_final_output": ["commit_shas_created"],
            },
            "rungs": [{"id": "endurance_10m", "time_budget_minutes": 10}],
            "competitor_requirements": {"required_capability_class": "tool_using_agent"},
        }
        args = types.SimpleNamespace(
            endurance_rung="endurance_10m",
            endurance_poll_seconds=1.0,
            watch=False,
        )
        config = types.SimpleNamespace(tools=types.SimpleNamespace(sandbox_root=str(repo)))
        track = types.SimpleNamespace(name="baseline_agent")

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
            report_path = workspace_root / artifact_root_rel / "baseline_agent" / "endurance_report.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps({"verification_runs": [], "remaining_blockers": [], "recovery_actions": []}),
                encoding="utf-8",
            )
            source_tracked = repo / "tracked.txt"
            source_tracked.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
            return {
                "record": {
                    "validity": "valid",
                    "invalid_reason": "",
                    "success": True,
                    "artifact_success": True,
                    "response_confirmed": True,
                    "timed_out": False,
                    "runaway_guarded": False,
                    "runner_error_present": False,
                },
                "detailed_row": {"run": {"tool_calls": 0, "usage": {}}},
                "transcript_rel": "transcripts/baseline_agent/endurance.md",
                "transcript_body": "done",
            }

        run_dir = asyncio.run(
            run_endurance_ladder(
                args=args,
                config=config,
                task_pack=pack,
                tracks=[track],
                run_id="endurance-source-leak",
                workspace_root=repo,
                runs_dir=self.tmp_path / "runs",
                quality_min=1,
                quality_max=5,
                run_task_entry=fake_run_task_entry,
            )
        )

        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        metrics = summary["competitors"]["baseline_agent"]
        self.assertEqual(metrics["validity"], "valid")
        self.assertEqual(metrics["invalid_reason"], "")
        self.assertFalse(metrics["source_repo_changed"])
        self.assertTrue(metrics["live_source_repo_changed"])

    def test_run_endurance_ladder_marks_source_snapshot_change_invalid(self) -> None:
        repo = self._init_dirty_repo()
        pack = {
            "id": "endurance-demo",
            "version": 1,
            "type": "endurance_ladder",
            "task_contract": {
                "goal": "Drain the repo.",
                "rules": ["Use guarded commits only."],
                "required_final_output": ["commit_shas_created"],
            },
            "rungs": [{"id": "endurance_10m", "time_budget_minutes": 10}],
            "competitor_requirements": {"required_capability_class": "tool_using_agent"},
        }
        args = types.SimpleNamespace(
            endurance_rung="endurance_10m",
            endurance_poll_seconds=1.0,
            watch=False,
        )
        config = types.SimpleNamespace(tools=types.SimpleNamespace(sandbox_root=str(repo)))
        track = types.SimpleNamespace(name="baseline_agent")

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
            report_path = workspace_root / artifact_root_rel / "baseline_agent" / "endurance_report.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps({"verification_runs": [], "remaining_blockers": [], "recovery_actions": []}),
                encoding="utf-8",
            )
            source_snapshot_tracked = workspace_root.parent.parent / "source-snapshot" / "tracked.txt"
            source_snapshot_tracked.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
            return {
                "record": {
                    "validity": "valid",
                    "invalid_reason": "",
                    "success": True,
                    "artifact_success": True,
                    "response_confirmed": True,
                    "timed_out": False,
                    "runaway_guarded": False,
                    "runner_error_present": False,
                },
                "detailed_row": {"run": {"tool_calls": 0, "usage": {}}},
                "transcript_rel": "transcripts/baseline_agent/endurance.md",
                "transcript_body": "done",
            }

        run_dir = asyncio.run(
            run_endurance_ladder(
                args=args,
                config=config,
                task_pack=pack,
                tracks=[track],
                run_id="endurance-source-snapshot-leak",
                workspace_root=repo,
                runs_dir=self.tmp_path / "runs",
                quality_min=1,
                quality_max=5,
                run_task_entry=fake_run_task_entry,
            )
        )

        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        metrics = summary["competitors"]["baseline_agent"]
        self.assertEqual(metrics["validity"], "invalid_environment")
        self.assertEqual(metrics["invalid_reason"], "source_repo_changed_during_isolated_run")
        self.assertTrue(metrics["source_repo_changed"])
        self.assertFalse(metrics["live_source_repo_changed"])

    def test_run_endurance_ladder_ignores_transient_live_source_prefix_changes(self) -> None:
        repo = self._init_dirty_repo()
        pack = {
            "id": "endurance-demo",
            "version": 1,
            "type": "endurance_ladder",
            "task_contract": {
                "goal": "Drain the repo.",
                "rules": ["Use guarded commits only."],
                "required_final_output": ["commit_shas_created"],
            },
            "rungs": [{"id": "endurance_10m", "time_budget_minutes": 10}],
            "competitor_requirements": {"required_capability_class": "tool_using_agent"},
        }
        args = types.SimpleNamespace(
            endurance_rung="endurance_10m",
            endurance_poll_seconds=1.0,
            watch=False,
        )
        config = types.SimpleNamespace(tools=types.SimpleNamespace(sandbox_root=str(repo)))
        track = types.SimpleNamespace(name="baseline_agent")

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
            report_path = workspace_root / artifact_root_rel / "baseline_agent" / "endurance_report.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps({"verification_runs": [], "remaining_blockers": [], "recovery_actions": []}),
                encoding="utf-8",
            )
            transient = repo / ".codex" / "background" / "heartbeat.json"
            transient.parent.mkdir(parents=True, exist_ok=True)
            transient.write_text("{\"alive\": true}\n", encoding="utf-8")
            return {
                "record": {
                    "validity": "valid",
                    "invalid_reason": "",
                    "success": True,
                    "artifact_success": True,
                    "response_confirmed": True,
                    "timed_out": False,
                    "runaway_guarded": False,
                    "runner_error_present": False,
                },
                "detailed_row": {"run": {"tool_calls": 0, "usage": {}}},
                "transcript_rel": "transcripts/baseline_agent/endurance.md",
                "transcript_body": "done",
            }

        run_dir = asyncio.run(
            run_endurance_ladder(
                args=args,
                config=config,
                task_pack=pack,
                tracks=[track],
                run_id="endurance-transient-live-ignore",
                workspace_root=repo,
                runs_dir=self.tmp_path / "runs",
                quality_min=1,
                quality_max=5,
                run_task_entry=fake_run_task_entry,
            )
        )

        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        metrics = summary["competitors"]["baseline_agent"]
        self.assertEqual(metrics["validity"], "valid")
        self.assertEqual(metrics["invalid_reason"], "")
        self.assertFalse(metrics["source_repo_changed"])
        self.assertFalse(metrics["live_source_repo_changed"])


if __name__ == "__main__":
    unittest.main()
