from __future__ import annotations

import json
from pathlib import Path

from thomas.demo import agent_comparison_suite as suite
from thomas.plugins import benchmark_program as benchmark_program_plugin


def test_load_suite_config_infers_tracked_cli_commands_from_fixed_depth(tmp_path: Path) -> None:
    cfg = {
        "id": "x",
        "agents": [
            {
                "id": "a1",
                "root": ".",
                "cli": {"fixed_subcommand_depth": {"alpha": 1, "beta": 2}},
            }
        ],
    }
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")

    loaded = suite.load_suite_config(path)
    assert loaded["tracked_cli_commands"] == ["alpha", "beta"]


def test_load_suite_config_preserves_competitor_catalog(tmp_path: Path) -> None:
    cfg = {
        "id": "x",
        "competitor_catalog": [{"id": "openclaw", "repo_url": "https://example.com/openclaw.git", "enabled": True}],
        "agents": [{"id": "thomas", "root": "."}],
    }
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    loaded = suite.load_suite_config(path)
    assert len(loaded["competitor_catalog"]) == 1
    assert loaded["competitor_catalog"][0]["id"] == "openclaw"


def test_load_suite_config_reads_test_suite_contract_path(tmp_path: Path) -> None:
    cfg = {
        "id": "x",
        "test_suite_contract_path": "demo/baselines/custom.contract.json",
        "agents": [{"id": "thomas", "root": "."}],
    }
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    loaded = suite.load_suite_config(path)
    assert loaded["test_suite_contract_path"] == "demo/baselines/custom.contract.json"


def test_load_suite_config_reads_execution_policy(tmp_path: Path) -> None:
    cfg = {
        "id": "x",
        "execution_policy": {
            "quality_is_king": True,
            "cycle_limit_disabled": True,
            "stop_condition": "Never stop on cycle count.",
        },
        "agents": [{"id": "thomas", "root": "."}],
    }
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    loaded = suite.load_suite_config(path)
    policy = dict(loaded["execution_policy"])
    assert policy["quality_is_king"] is True
    assert policy["cycle_limit_disabled"] is True
    assert policy["stop_condition"] == "Never stop on cycle count."


def test_load_suite_config_reads_head_to_head_tie_policy(tmp_path: Path) -> None:
    cfg = {
        "id": "x",
        "head_to_head_tie_policy": "exclude",
        "agents": [{"id": "thomas", "root": "."}],
    }
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    loaded = suite.load_suite_config(path)
    assert loaded["head_to_head_tie_policy"] == "exclude"


def test_default_suite_config_wires_benchmark_evidence_globs_for_thomas_and_openclaw() -> None:
    loaded = suite.load_suite_config(suite.DEFAULT_SUITE_CONFIG)
    agents = {
        str(agent.get("id") or "").strip(): dict(agent)
        for agent in list(loaded.get("agents") or [])
        if str(agent.get("id") or "").strip()
    }
    assert agents["thomas"]["benchmark_evidence_globs"] == ["demo/agentic-runs/*/benchmark_results.raw.json"]
    assert agents["openclaw"]["benchmark_evidence_globs"] == ["demo/agentic-runs/*/benchmark_results.raw.json"]


def test_assertion_resolution_and_ops() -> None:
    payload = {"a": {"b": [{"id": "x"}, {"id": "y"}]}, "num": 4}
    assert suite._resolve_path_value(payload, "a.b.1.id") == "y"
    assert suite._assertion_ok(4, "eq", 4) is True
    assert suite._assertion_ok(4, "gte", 3) is True
    assert suite._assertion_ok("", "falsy", False) is True
    assert suite._assertion_ok("ok", "truthy", True) is True


def test_collect_benchmark_summary_uses_alias_and_aggregates(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    for idx, score in enumerate((40.0, 60.0), start=1):
        run_dir = runs / f"run-{idx}"
        run_dir.mkdir(parents=True, exist_ok=True)
        scorecard = {
            "summary": {
                "competitors": {
                    "thomas_os": {
                        "weighted_score": score,
                        "success_rate": 0.5 + (idx * 0.1),
                        "evidence_coverage": 1.0,
                        "avg_elapsed_seconds": 10.0 + idx,
                        "credibility_weighted_score": score,
                    }
                }
            }
        }
        (run_dir / "scorecard.json").write_text(json.dumps(scorecard), encoding="utf-8")

    agent = {
        "id": "thomas",
        "benchmark_scorecard_globs": [str((runs / "*" / "scorecard.json").as_posix())],
        "benchmark_aliases": ["thomas_os"],
    }
    summary = suite._collect_benchmark_summary(agent, suite_root=tmp_path)
    assert summary["runs_count"] == 2
    assert summary["weighted_score_mean"] == 50.0
    assert summary["weighted_score_stddev"] == 10.0


def test_collect_benchmark_summary_reads_raw_rows_for_cost_signals(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    run_dir = runs / "run-1"
    run_dir.mkdir(parents=True, exist_ok=True)

    scorecard = {
        "summary": {
            "competitors": {
                "thomas_os": {
                    "weighted_score": 80.0,
                    "success_rate": 1.0,
                    "evidence_coverage": 1.0,
                    "avg_elapsed_seconds": 12.0,
                    "credibility_weighted_score": 80.0,
                }
            }
        }
    }
    raw_rows = [
        {
            "track": "thomas_os",
            "run": {
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
                "tool_calls": 2,
                "elapsed_seconds": 4.0,
            },
            "success": True,
        },
        {
            "track": "thomas_os",
            "run": {
                "usage": {"prompt_tokens": 80, "completion_tokens": 20, "total_tokens": 100},
                "tool_calls": 1,
                "elapsed_seconds": 6.0,
            },
            "success": False,
        },
    ]
    (run_dir / "scorecard.json").write_text(json.dumps(scorecard), encoding="utf-8")
    (run_dir / "benchmark_results.raw.json").write_text(json.dumps(raw_rows), encoding="utf-8")

    agent = {
        "id": "thomas",
        "benchmark_scorecard_globs": [str((runs / "*" / "scorecard.json").as_posix())],
        "benchmark_raw_globs": [str((runs / "*" / "benchmark_results.raw.json").as_posix())],
        "benchmark_aliases": ["thomas_os"],
    }
    summary = suite._collect_benchmark_summary(agent, suite_root=tmp_path)
    assert summary["raw_rows_count"] == 2
    assert summary["raw_total_tokens_mean"] == 125.0
    assert summary["raw_tool_calls_mean"] == 1.5
    assert summary["raw_tokens_per_success"] == 250.0


def test_collect_benchmark_evidence_reads_raw_rows_by_alias(tmp_path: Path) -> None:
    runs = tmp_path / "runs" / "run-1"
    runs.mkdir(parents=True, exist_ok=True)
    raw_rows = [
        {
            "task_id": "prog.001",
            "track": "thomas",
            "success": True,
            "quality_score": 96.0,
            "evidence": "transcripts/thomas/prog.001.md",
        },
        {
            "task_id": "prog.001",
            "track": "openclaw",
            "success": False,
            "quality_score": 20.0,
            "evidence": "transcripts/openclaw/prog.001.md",
        },
        {
            "task_id": "prog.002",
            "track": "thomas_os",
            "checks": {"success": True},
        },
    ]
    evidence_file = runs / "benchmark_results.raw.json"
    evidence_file.write_text(json.dumps(raw_rows), encoding="utf-8")
    pattern = str((tmp_path / "runs" / "*" / "benchmark_results.raw.json").as_posix())

    thomas_evidence = suite._collect_benchmark_evidence(
        {"id": "thomas", "benchmark_aliases": ["thomas_os"], "benchmark_evidence_globs": [pattern]},
        suite_root=tmp_path,
    )
    assert thomas_evidence["checks"]["prog.001"]["pass"] is True
    assert thomas_evidence["checks"]["prog.001"]["score"] == 96.0
    assert thomas_evidence["checks"]["prog.001"]["source"] == "transcripts/thomas/prog.001.md"
    assert thomas_evidence["checks"]["prog.002"]["pass"] is True

    openclaw_evidence = suite._collect_benchmark_evidence(
        {"id": "openclaw", "benchmark_aliases": ["openclaw"], "benchmark_evidence_globs": [pattern]},
        suite_root=tmp_path,
    )
    assert openclaw_evidence["checks"]["prog.001"]["pass"] is False
    assert openclaw_evidence["checks"]["prog.001"]["score"] == 20.0
    assert "prog.002" not in openclaw_evidence["checks"]


def test_compute_token_efficiency_returns_blended_score() -> None:
    benchmark = {
        "raw_tokens_per_success": 320.0,
        "raw_total_tokens_mean": 180.0,
        "raw_prompt_tokens_mean": 120.0,
        "raw_completion_tokens_mean": 60.0,
        "raw_success_rate_mean": 0.75,
    }
    probe = {"pass_rate": 1.0}
    payload = suite._compute_token_efficiency(benchmark=benchmark, cost_probe=probe)
    assert payload["overall_score"] is not None
    assert payload["effective_tokens_per_success"] == 320.0
    assert payload["telemetry_coverage"] == 1.0


def test_run_probe_suite_collects_repeats_and_throughput(tmp_path: Path) -> None:
    agent = {
        "performance_probes": [
            {
                "id": "x",
                "repeat": 3,
                "command": [
                    "{python}",
                    "-c",
                    "import json; print(json.dumps({'total': 10, 'ok': True}))",
                ],
                "throughput_numerator_path": "total",
                "assertions": [
                    {"path": "total", "op": "eq", "value": 10},
                    {"path": "ok", "op": "eq", "value": True},
                ],
            }
        ]
    }
    summary = suite._run_probe_suite(agent, agent_root=tmp_path, probe_key="performance_probes")
    assert summary["total_runs"] == 3
    assert summary["passed_runs"] == 3
    assert summary["failed_runs"] == 0
    assert summary["pass_rate"] == 1.0
    assert summary["throughput"]["mean"] is not None


def test_count_regex_hits_respects_ignore_globs(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "keep.py").write_text("exec(code)\n", encoding="utf-8")
    (src / "skip.py").write_text("exec(code)\n", encoding="utf-8")

    all_hits = suite._count_regex_hits([src], [r"(?<!\.)\bexec\s*\("])
    kept_hits = suite._count_regex_hits([src], [r"(?<!\.)\bexec\s*\("], ignore_globs=["**/skip.py"])

    assert all_hits["total_hits"] == 2
    assert kept_hits["total_hits"] == 1
    assert kept_hits["files_with_hits"] == 1


def test_risky_regex_ignores_method_exec_calls(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "db.ts").write_text("db.exec(`SELECT 1`)\n", encoding="utf-8")
    hits = suite._count_regex_hits([src], [r"(?<!\.)\bexec\s*\("])
    assert hits["total_hits"] == 0


def test_build_metric_rows_and_focus_gaps() -> None:
    metric_specs = {
        "m1": suite.MetricSpec("m1", "code_surface", "higher_is_better", 1.0, "x"),
        "m2": suite.MetricSpec("m2", "integrity", "lower_is_better", 1.0, "y"),
    }
    agents = [
        {"id": "thomas", "metrics": {"m1": 5, "m2": 5}},
        {"id": "openclaw", "metrics": {"m1": 7, "m2": 3}},
    ]
    rows = suite._build_metric_rows(metric_specs=metric_specs, agents=agents)
    scoreboard = suite._build_scoreboard(rows, agents=agents)
    assert scoreboard["wins_by_agent"]["openclaw"] == 2
    gaps = suite._focus_gaps(rows, focus_agent="thomas", top_n=10)
    assert len(gaps) == 2
    assert gaps[0]["metric"] in {"m1", "m2"}


def test_build_scoreboard_ignores_single_agent_metrics_in_composite_scoring() -> None:
    rows = [
        {
            "metric": "single_only",
            "category": "code_surface",
            "weight": 10.0,
            "participants": ["thomas"],
            "winners": ["thomas"],
            "normalized": {"thomas": 1.0, "openclaw": 0.0},
            "values": {"thomas": 7, "openclaw": None},
        },
        {
            "metric": "shared",
            "category": "code_surface",
            "weight": 1.0,
            "participants": ["thomas", "openclaw"],
            "winners": ["thomas"],
            "normalized": {"thomas": 1.0, "openclaw": 0.0},
            "values": {"thomas": 5, "openclaw": 1},
        },
    ]
    agents = [{"id": "thomas", "metrics": {}}, {"id": "openclaw", "metrics": {}}]
    scoreboard = suite._build_scoreboard(rows, agents=agents)
    assert scoreboard["measured_metrics"] == 1
    assert scoreboard["max_weight_total"] == 1.0
    top = scoreboard["ranking"][0]
    assert top["agent"] == "thomas"
    assert top["composite_score"] == 100.0
    assert top["comparable_metrics_total"] == 1


def test_evaluate_benchmark_program_computes_lane_scores_and_verdicts() -> None:
    contract = {
        "benchmark_program": {"id": "bp", "lane_weights": {"quick": 0.4, "dynamic": 0.6}},
        "benchmark_families": [
            {
                "id": "coverage_and_correctness",
                "name": "Foundation Integrity",
                "default_test_mode": "quick",
                "description": "Foundation checks.",
            },
            {
                "id": "task_quality",
                "name": "Task Quality",
                "default_test_mode": "dynamic",
                "description": "Task checks.",
            },
        ],
        "catalog_checks": [
            {
                "id": "core.quick",
                "category": "coverage_and_correctness",
                "implementation_mode": "contract_rule_v1",
                "test_mode": "quick",
                "benchmark_family": "coverage_and_correctness",
            },
            {
                "id": "prog.001",
                "category": "task_quality",
                "implementation_mode": "evidence_required_v1",
                "test_mode": "dynamic",
                "benchmark_family": "task_quality",
                "evidence_id": "prog.001",
                "pass_score_gte": 90.0,
            },
        ],
    }
    result = {
        "suite": {"competitor_catalog_count": 1},
        "prediction_evo_scope": {},
        "metric_board": [
            {
                "metric": "tests.files",
                "category": "test_rigor",
                "test_mode": "quick",
                "values": {"a": 10, "b": 5},
                "winners": ["a"],
            },
            {
                "metric": "performance.load.pass_rate",
                "category": "performance_load",
                "test_mode": "dynamic",
                "values": {"a": 1.0, "b": 0.5},
                "winners": ["a"],
            },
        ],
        "agents": [
            {
                "id": "a",
                "metrics": {
                    "tests.files": 10,
                    "tests.loc": 20,
                    "production.strict_checks.pass_rate": 1.0,
                    "performance.load.pass_rate": 1.0,
                    "resilience.probes.pass_rate": 1.0,
                    "security.probes.pass_rate": 1.0,
                    "cost.probes.pass_rate": 1.0,
                    "benchmark.runs_count": 1,
                    "integrity.python_syntax_errors": 0,
                    "integrity.invalid_json_files": 0,
                    "integrity.missing_required_paths": 0,
                    "integrity.empty_production_asset_files": 0,
                    "security.secret_like_hits": 0,
                    "security.risky_construct_hits_count": 0,
                    "benchmark.weighted_score_stddev": 0.05,
                    "benchmark.success_rate_stddev": 0.05,
                    "cost.token_efficiency_score": 70.0,
                },
                "benchmark_evidence": {"checks": {"prog.001": {"pass": True, "score": 100}}},
            },
            {
                "id": "b",
                "metrics": {
                    "tests.files": 5,
                    "tests.loc": 10,
                    "production.strict_checks.pass_rate": 0.0,
                    "performance.load.pass_rate": 0.5,
                    "resilience.probes.pass_rate": 0.5,
                    "security.probes.pass_rate": 0.5,
                    "cost.probes.pass_rate": 0.5,
                    "benchmark.runs_count": 1,
                    "integrity.python_syntax_errors": 0,
                    "integrity.invalid_json_files": 0,
                    "integrity.missing_required_paths": 0,
                    "integrity.empty_production_asset_files": 0,
                    "security.secret_like_hits": 1,
                    "security.risky_construct_hits_count": 1,
                    "benchmark.weighted_score_stddev": 0.8,
                    "benchmark.success_rate_stddev": 0.8,
                },
                "benchmark_evidence": {"checks": {"prog.001": {"pass": False, "score": 10}}},
            },
        ],
    }
    contract_eval = {
        "scores": {
            "agents": [
                {"agent": "a", "token_efficiency_score": 70.0},
                {"agent": "b", "token_efficiency_score": None},
            ]
        }
    }
    program = benchmark_program_plugin.evaluate_benchmark_program(
        contract=contract, result=result, contract_evaluation=contract_eval
    )
    assert program["id"] == "bp"
    assert len(program["family_catalog"]) == 2
    assert len(program["ranking"]) == 2
    assert program["ranking"][0]["agent"] == "a"
    assert "governance_verdict" in program["ranking"][0]
    assert "task_quality" in program["ranking"][0]["family_scores"]


def test_build_competitor_pressure_ranks_top_threat() -> None:
    rows = [
        {
            "participants": ["thomas", "comp_a"],
            "winners": ["comp_a"],
        },
        {
            "participants": ["thomas", "comp_b"],
            "winners": ["thomas"],
        },
        {
            "participants": ["thomas", "comp_a"],
            "winners": ["comp_a"],
        },
    ]
    scoreboard = {
        "ranking": [
            {"agent": "thomas", "composite_score": 70.0},
            {"agent": "comp_a", "composite_score": 80.0},
            {"agent": "comp_b", "composite_score": 60.0},
        ]
    }
    pressure = suite._build_competitor_pressure(rows=rows, scoreboard=scoreboard, focus_agent="thomas")
    assert pressure["top_threats"][0]["competitor"] == "comp_a"
    assert pressure["top_threats"][0]["metrics_beating_focus"] == 2


def test_collect_agent_metrics_uses_fallback_probes_when_unconfigured(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "main.py").write_text("print('ok')\n", encoding="utf-8")

    runs = tmp_path / "runs" / "run-1"
    runs.mkdir(parents=True, exist_ok=True)
    scorecard = {
        "summary": {
            "competitors": {
                "agent_a": {
                    "weighted_score": 75.0,
                    "success_rate": 0.5,
                    "evidence_coverage": 1.0,
                    "avg_elapsed_seconds": 8.0,
                    "credibility_weighted_score": 74.0,
                }
            }
        }
    }
    raw_rows = [
        {
            "task_id": "prog.001",
            "track": "agent_a",
            "run": {
                "usage": {"prompt_tokens": 120, "completion_tokens": 60, "total_tokens": 180},
                "tool_calls": 2,
                "elapsed_seconds": 5.0,
            },
            "success": True,
            "quality_score": 95.0,
            "evidence": "transcripts/agent_a/prog.001.md",
        }
    ]
    (runs / "scorecard.json").write_text(json.dumps(scorecard), encoding="utf-8")
    (runs / "benchmark_results.raw.json").write_text(json.dumps(raw_rows), encoding="utf-8")

    agent = {
        "id": "agent_a",
        "root": ".",
        "source_roots": ["src"],
        "test_roots": ["src"],
        "browser_roots": [],
        "plugin_roots": [],
        "gateway_roots": [],
        "cli_roots": [],
        "mobile_roots": ["."],
        "cli": {"fixed_top_level_commands": 1, "fixed_subcommand_depth": {"x": 1}},
        "strict_checks": [],
        "benchmark_scorecard_globs": [str((tmp_path / "runs" / "*" / "scorecard.json").as_posix())],
        "benchmark_raw_globs": [str((tmp_path / "runs" / "*" / "benchmark_results.raw.json").as_posix())],
        "benchmark_evidence_globs": [str((tmp_path / "runs" / "*" / "benchmark_results.raw.json").as_posix())],
        "benchmark_aliases": ["agent_a"],
    }

    payload = suite._collect_agent_metrics(
        agent,
        tracked_commands=["x"],
        suite_root=tmp_path,
    )
    assert payload["performance_probe"]["total_runs"] > 0
    assert payload["resilience_probe"]["total_runs"] > 0
    assert payload["security_probe"]["total_runs"] > 0
    assert payload["cost_probe"]["total_runs"] > 0
    assert payload["metrics"]["cost.probes.pass_rate"] == 1.0
    assert payload["metrics"]["performance.load.avg_elapsed_seconds"] is None
    assert payload["metrics"]["resilience.probes.avg_elapsed_seconds"] is None
    assert payload["metrics"]["security.probes.avg_elapsed_seconds"] is None
    assert payload["metrics"]["maintainability.large_code_files_over_800"] == 0.0
    assert payload["metrics"]["maintainability.large_code_files_count_over_800"] == 0
    assert payload["metrics"]["security.risky_construct_hits"] == 0.0
    assert payload["metrics"]["security.risky_construct_hits_count"] == 0
    assert "cost.token_efficiency_score" in payload["metrics"]
    assert payload["metrics"]["cost.token_efficiency_telemetry_coverage"] >= 0.0
    assert isinstance(payload["version_info"], dict)
    assert isinstance(payload["model_snapshot"], dict)
    assert payload["benchmark_evidence"]["checks"]["prog.001"]["pass"] is True
    assert payload["benchmark_evidence"]["checks"]["prog.001"]["score"] == 95.0


def test_collect_agent_metrics_counts_test_dataset_roots(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "main.py").write_text("print('ok')\n", encoding="utf-8")
    dataset = tmp_path / "dataset"
    dataset.mkdir(parents=True, exist_ok=True)
    (dataset / "case_0001.json").write_text('{\n  "id": 1,\n  "name": "case"\n}\n', encoding="utf-8")
    (dataset / "case_0002.json").write_text('{\n  "id": 2,\n  "name": "case"\n}\n', encoding="utf-8")

    agent = {
        "id": "agent_ds",
        "root": ".",
        "source_roots": ["src", "dataset"],
        "test_roots": ["src"],
        "test_dataset_roots": ["dataset"],
        "browser_roots": [],
        "plugin_roots": [],
        "gateway_roots": [],
        "cli_roots": [],
        "mobile_roots": ["."],
        "cli": {"fixed_top_level_commands": 1, "fixed_subcommand_depth": {"x": 1}},
        "strict_checks": [],
        "benchmark_scorecard_globs": [],
        "benchmark_aliases": [],
    }
    payload = suite._collect_agent_metrics(agent, tracked_commands=["x"], suite_root=tmp_path)
    metrics = dict(payload.get("metrics") or {})
    assert int(metrics.get("tests.files") or 0) == 2
    assert int(metrics.get("tests.dataset_files") or 0) == 2
    assert int(metrics.get("tests.dataset_loc") or 0) > 0
    assert float(metrics.get("tests.to_code_loc_ratio") or 0.0) > 0.0


def test_collect_model_snapshot_command_records_daily_model() -> None:
    agent = {
        "id": "agent_x",
        "model_snapshot_required": True,
        "model_snapshot_command": [
            "{python}",
            "-c",
            "import json; print(json.dumps({'model':'demo-model','provider':'demo','profile':'demo-profile'}))",
        ],
    }
    snap = suite._collect_model_snapshot(agent, agent_root=Path("."))
    assert snap["ok"] is True
    assert snap["model"] == "demo-model"
    assert snap["day_utc"]


def test_collect_git_version_info_returns_none_for_non_git_root(tmp_path: Path) -> None:
    info = suite._collect_git_version_info(tmp_path, sync_cfg={"enabled": True})
    assert info["kind"] == "none"


def test_materialize_competitor_catalog_agents_adds_missing_agent(tmp_path: Path) -> None:
    comp_root = tmp_path / "comp_repo" / "src"
    comp_root.mkdir(parents=True, exist_ok=True)
    (comp_root / "main.py").write_text("print('x')\n", encoding="utf-8")
    cfg = {
        "agents": [{"id": "thomas", "root": "."}],
        "competitor_catalog": [{"id": "comp", "root": str(comp_root.parent), "enabled": True}],
    }
    agents, prep = suite._materialize_competitor_catalog_agents(suite_config=cfg, suite_root=tmp_path)
    ids = {a["id"] for a in agents}
    assert "comp" in ids
    prep_row = [r for r in prep if r["id"] == "comp"][0]
    assert prep_row["status"] == "ok"


def test_update_competitor_registry_records_last_test_and_version(tmp_path: Path) -> None:
    registry_path = tmp_path / "competitor_registry.json"
    registry_md_path = tmp_path / "competitor_registry.md"
    result_json = tmp_path / "result.json"
    result_md = tmp_path / "result.md"

    result = {
        "computed_at_utc": "2026-02-21T18:30:00Z",
        "suite": {"id": "suite-x"},
        "scoreboard": {
            "total_metrics": 10,
            "measured_metrics": 9,
            "tie_metrics": 1,
            "ranking": [
                {"agent": "thomas", "rank": 1, "wins": 5, "composite_score": 90.0},
                {"agent": "openclaw", "rank": 2, "wins": 2, "composite_score": 70.0},
            ],
        },
        "agents": [
            {
                "id": "thomas",
                "label": "Thomas",
                "root": "C:/repo/thomas",
                "version_info": {"kind": "git", "local_head": "aaa", "is_up_to_date": True},
                "model_snapshot": {"ok": True, "day_utc": "2026-02-21", "model": "m1"},
            },
            {
                "id": "openclaw",
                "label": "OpenClaw",
                "root": "C:/repo/openclaw",
                "version_info": {"kind": "git", "local_head": "bbb", "is_up_to_date": False},
                "model_snapshot": {"ok": True, "day_utc": "2026-02-21", "model": "m2"},
            },
        ],
    }

    suite._update_competitor_registry(
        result=result,
        registry_path=registry_path,
        registry_md_path=registry_md_path,
        result_json_path=result_json,
        result_md_path=result_md,
    )

    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    assert payload["updated_at_utc"] == "2026-02-21T18:30:00Z"
    assert payload["competitors"]["openclaw"]["version"]["local_head"] == "bbb"
    assert payload["competitors"]["openclaw"]["last_result_json"] == str(result_json)
    assert registry_md_path.exists()


def test_build_suite_result_end_to_end_with_small_local_agents(tmp_path: Path) -> None:
    a_root = tmp_path / "a"
    b_root = tmp_path / "b"
    (a_root / "src").mkdir(parents=True, exist_ok=True)
    (b_root / "src").mkdir(parents=True, exist_ok=True)
    (a_root / "src" / "main.py").write_text("print('a')\n", encoding="utf-8")
    (b_root / "src" / "main.py").write_text("print('b')\nprint('b2')\n", encoding="utf-8")

    cfg = {
        "id": "mini",
        "version": 1,
        "test_suite_contract_path": "demo/baselines/test.contract.json",
        "tracked_cli_commands": ["x"],
        "agents": [
            {
                "id": "a",
                "root": str(a_root),
                "source_roots": ["src"],
                "test_roots": ["src"],
                "browser_roots": [],
                "plugin_roots": [],
                "gateway_roots": [],
                "cli_roots": [],
                "mobile_roots": ["."],
                "cli": {"fixed_top_level_commands": 1, "fixed_subcommand_depth": {"x": 1}},
                "strict_checks": [],
                "benchmark_scorecard_globs": [],
                "benchmark_aliases": [],
            },
            {
                "id": "b",
                "root": str(b_root),
                "source_roots": ["src"],
                "test_roots": ["src"],
                "browser_roots": [],
                "plugin_roots": [],
                "gateway_roots": [],
                "cli_roots": [],
                "mobile_roots": ["."],
                "cli": {"fixed_top_level_commands": 2, "fixed_subcommand_depth": {"x": 2}},
                "strict_checks": [],
                "benchmark_scorecard_globs": [],
                "benchmark_aliases": [],
            },
        ],
    }

    suite_path = tmp_path / "demo" / "baselines" / "mini.json"
    suite_path.parent.mkdir(parents=True, exist_ok=True)
    suite_path.write_text(json.dumps(cfg), encoding="utf-8")
    contract_path = tmp_path / "demo" / "baselines" / "test.contract.json"
    contract_path.write_text(
        json.dumps(
            {
                "id": "test-contract",
                "version": 1,
                "runtime_metric_contract": {"include_all_runtime_metrics": True},
                "catalog_checks": [
                    {
                        "id": "agentic.001",
                        "category": "agentic_native",
                        "title": "Hard-constraint violation rate across full runs.",
                        "implementation_state": "planned",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    loaded = suite.load_suite_config(suite_path)
    result = suite.build_suite_result(
        suite_config=loaded,
        suite_path=suite_path,
        focus_agent="a",
        top_gaps=10,
    )
    assert result["suite"]["id"] == "mini"
    assert len(result["agents"]) == 2
    assert int(result["scoreboard"]["total_metrics"]) > 0
    assert "prediction_evo_scope" in result
    assert "competitor_pressure" in result["focus"]
    assert "test_suite_contract" in result
    contract = dict(result["test_suite_contract"])
    assert contract["contract_id"] == "test-contract"
    assert int(dict(contract["runtime_metrics"]).get("total") or 0) > 0
    assert "scores" in contract
    assert "overall_suite_scoreboard" in result
    assert "benchmark_program" in result
    benchmark = dict(result["benchmark_program"])
    assert "ranking" in benchmark
    overall_rows = list(dict(result["overall_suite_scoreboard"]).get("ranking") or [])
    assert len(overall_rows) == 2
    assert isinstance(overall_rows[0].get("overall_suite_score"), float)
    assert "head_to_head_decisive_score" in overall_rows[0]
    assert isinstance(overall_rows[0].get("quick_suite_score"), float)
    assert isinstance(overall_rows[0].get("dynamic_suite_score"), float)
    assert isinstance(overall_rows[0].get("human_suite_score"), float)
    assert "overall_benchmark_capability_score" in overall_rows[0]
    assert "governance_verdict" in overall_rows[0]
    policy = dict(result["suite"]["execution_policy"])
    assert policy["quality_is_king"] is True
    assert policy["cycle_limit_disabled"] is True
