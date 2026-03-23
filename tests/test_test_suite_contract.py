from __future__ import annotations

from pathlib import Path

from thomas.plugins import test_suite_contract as contract


def test_load_test_suite_contract_missing_file(tmp_path: Path) -> None:
    payload = contract.load_test_suite_contract(tmp_path / "missing.contract.json")
    assert payload["id"] == "missing"
    assert payload["catalog_checks"] == []
    assert payload["errors"]


def test_evaluate_test_suite_contract_marks_catalog_checks_passed() -> None:
    sample_contract = {
        "id": "c1",
        "version": 1,
        "catalog_checks": [
            {
                "id": "core.001",
                "category": "coverage_and_correctness",
                "title": "x",
                "implementation_state": "implemented",
            },
            {"id": "agentic.001", "category": "agentic_native", "title": "y", "implementation_state": "implemented"},
        ],
    }
    result = {
        "suite": {"competitor_catalog_count": 1},
        "focus": {"competitor_pressure": {"ranked_competitors": [{"competitor": "x"}]}},
        "prediction_evo_scope": {},
        "agents": [
            {
                "id": "thomas",
                "metrics": {
                    "tests.files": 1,
                    "tests.loc": 10,
                    "cli.top_level_commands": 1,
                    "browser.files": 1,
                    "extensions.directories": 1,
                    "gateway.openai_chat_completions.files": 1,
                    "gateway.responses.files": 1,
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
                },
            }
        ],
        "metric_board": [
            {"metric": "tests.files", "values": {"thomas": 1}, "participants": ["thomas", "comp"]},
            {"metric": "tests.loc", "values": {"thomas": 10}, "participants": ["thomas", "comp"]},
        ],
    }
    evaluation = contract.evaluate_test_suite_contract(contract=sample_contract, result=result, focus_agent="thomas")
    assert evaluation["summary"]["implemented_total"] == 4
    assert evaluation["summary"]["catalog_passed_total"] == 2
    assert evaluation["summary"]["catalog_failed_total"] == 0


def test_head_to_head_score_counts_unique_runtime_metrics() -> None:
    sample_contract = {
        "id": "c2",
        "version": 1,
        "catalog_checks": [],
    }
    result = {
        "suite": {"competitor_catalog_count": 1},
        "focus": {},
        "prediction_evo_scope": {},
        "agents": [
            {"id": "thomas", "metrics": {}},
            {"id": "openclaw", "metrics": {}},
        ],
        "metric_board": [
            {
                "metric": "m_only_thomas",
                "preference": "higher_is_better",
                "values": {"thomas": 1, "openclaw": None},
                "participants": ["thomas"],
                "winners": ["thomas"],
            },
            {
                "metric": "m_only_openclaw",
                "preference": "higher_is_better",
                "values": {"thomas": None, "openclaw": 1},
                "participants": ["openclaw"],
                "winners": ["openclaw"],
            },
            {
                "metric": "m_neither",
                "preference": "higher_is_better",
                "values": {"thomas": None, "openclaw": None},
                "participants": [],
                "winners": [],
            },
        ],
    }
    evaluation = contract.evaluate_test_suite_contract(
        contract=sample_contract,
        result=result,
        focus_agent="thomas",
        head_to_head_pair=["thomas", "openclaw"],
    )
    h2h = dict(dict(evaluation["scores"]).get("head_to_head") or {})
    assert bool(h2h.get("enabled")) is True
    assert int(h2h.get("counted_metrics") or 0) == 2
    assert float(h2h.get("agent_a_score") or 0.0) == 50.0
    assert float(h2h.get("agent_b_score") or 0.0) == 50.0
    assert int(h2h.get("decisive_counted_metrics") or 0) == 2
    assert float(h2h.get("decisive_agent_a_score") or 0.0) == 50.0
    assert float(h2h.get("decisive_agent_b_score") or 0.0) == 50.0
    token_h2h = dict(dict(dict(evaluation["scores"]).get("token_efficiency") or {}).get("head_to_head") or {})
    assert int(token_h2h.get("counted_metrics") or 0) == 0


def test_head_to_head_tie_policy_exclude_removes_ties_from_denominator() -> None:
    sample_contract = {"id": "c-tie-policy", "version": 1, "catalog_checks": []}
    result = {
        "suite": {"competitor_catalog_count": 1, "head_to_head_tie_policy": "exclude"},
        "focus": {},
        "prediction_evo_scope": {},
        "agents": [
            {"id": "thomas", "metrics": {}},
            {"id": "openclaw", "metrics": {}},
        ],
        "metric_board": [
            {
                "metric": "m_tie",
                "preference": "higher_is_better",
                "values": {"thomas": 1, "openclaw": 1},
                "participants": ["thomas", "openclaw"],
                "winners": ["thomas", "openclaw"],
                "test_mode": "quick",
            },
            {
                "metric": "m_win",
                "preference": "higher_is_better",
                "values": {"thomas": 2, "openclaw": 1},
                "participants": ["thomas", "openclaw"],
                "winners": ["thomas"],
                "test_mode": "quick",
            },
        ],
    }
    evaluation = contract.evaluate_test_suite_contract(
        contract=sample_contract,
        result=result,
        focus_agent="thomas",
        head_to_head_pair=["thomas", "openclaw"],
    )
    h2h = dict(dict(evaluation["scores"]).get("head_to_head") or {})
    assert h2h.get("tie_policy") == "exclude"
    assert int(h2h.get("counted_metrics") or 0) == 1
    assert int(h2h.get("ties_observed") or 0) == 1
    assert float(h2h.get("agent_a_score") or 0.0) == 100.0
    assert float(h2h.get("agent_b_score") or 0.0) == 0.0
    assert int(h2h.get("decisive_counted_metrics") or 0) == 1
    assert float(h2h.get("decisive_agent_a_score") or 0.0) == 100.0
    assert float(h2h.get("decisive_agent_b_score") or 0.0) == 0.0


def test_lane_suite_scores_and_h2h_mode_breakdown_are_reported() -> None:
    sample_contract = {
        "id": "c-lanes",
        "version": 1,
        "catalog_checks": [
            {
                "id": "core.quick",
                "category": "coverage_and_correctness",
                "test_mode": "quick",
                "title": "quick check",
                "implementation_state": "implemented",
            },
            {
                "id": "core.dynamic",
                "category": "performance_and_cost",
                "test_mode": "dynamic",
                "title": "dynamic check",
                "implementation_state": "implemented",
            },
        ],
    }
    result = {
        "suite": {"competitor_catalog_count": 1},
        "focus": {},
        "prediction_evo_scope": {},
        "agents": [
            {
                "id": "thomas",
                "metrics": {
                    "tests.files": 10,
                    "tests.loc": 100,
                    "cli.top_level_commands": 5,
                    "browser.files": 1,
                    "extensions.directories": 1,
                    "gateway.openai_chat_completions.files": 1,
                    "gateway.responses.files": 1,
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
                },
            },
            {
                "id": "openclaw",
                "metrics": {
                    "tests.files": 1,
                    "tests.loc": 5,
                    "cli.top_level_commands": 1,
                    "browser.files": 0,
                    "extensions.directories": 0,
                    "gateway.openai_chat_completions.files": 0,
                    "gateway.responses.files": 0,
                    "production.strict_checks.pass_rate": 0.0,
                    "performance.load.pass_rate": 0.0,
                    "resilience.probes.pass_rate": 0.0,
                    "security.probes.pass_rate": 0.0,
                    "cost.probes.pass_rate": 0.0,
                    "benchmark.runs_count": 0,
                    "integrity.python_syntax_errors": 1,
                    "integrity.invalid_json_files": 1,
                    "integrity.missing_required_paths": 1,
                    "integrity.empty_production_asset_files": 1,
                },
            },
        ],
        "metric_board": [
            {
                "metric": "tests.files",
                "category": "test_rigor",
                "test_mode": "quick",
                "preference": "higher_is_better",
                "values": {"thomas": 10, "openclaw": 1},
                "participants": ["thomas", "openclaw"],
                "winners": ["thomas"],
            },
            {
                "metric": "performance.load.pass_rate",
                "category": "performance_load",
                "test_mode": "dynamic",
                "preference": "higher_is_better",
                "values": {"thomas": 1.0, "openclaw": 0.0},
                "participants": ["thomas", "openclaw"],
                "winners": ["thomas"],
            },
        ],
    }
    evaluation = contract.evaluate_test_suite_contract(
        contract=sample_contract,
        result=result,
        focus_agent="thomas",
        head_to_head_pair=["thomas", "openclaw"],
    )
    h2h = dict(dict(evaluation["scores"]).get("head_to_head") or {})
    h2h_by_mode = dict(h2h.get("by_mode") or {})
    assert int(dict(h2h_by_mode.get("quick") or {}).get("counted_metrics") or 0) == 1
    assert int(dict(h2h_by_mode.get("dynamic") or {}).get("counted_metrics") or 0) == 1

    score_rows = list(dict(evaluation.get("scores") or {}).get("agents") or [])
    thomas_row = next(row for row in score_rows if row.get("agent") == "thomas")
    assert float(thomas_row.get("quick_suite_score") or 0.0) > 0.0
    assert float(thomas_row.get("dynamic_suite_score") or 0.0) > 0.0
    mode_rankings = dict(dict(evaluation.get("scores") or {}).get("mode_rankings") or {})
    assert bool(mode_rankings.get("quick"))
    assert bool(mode_rankings.get("dynamic"))


def test_token_efficiency_head_to_head_prefers_lower_token_cost() -> None:
    sample_contract = {"id": "c3", "version": 1, "catalog_checks": []}
    result = {
        "suite": {"competitor_catalog_count": 1},
        "focus": {},
        "prediction_evo_scope": {},
        "agents": [
            {
                "id": "thomas",
                "metrics": {
                    "cost.token_efficiency_score": 82.0,
                    "cost.token_efficiency_tokens_per_success_effective": 300.0,
                    "cost.token_efficiency_telemetry_coverage": 1.0,
                    "cost.benchmark_tokens_per_success": 300.0,
                    "cost.benchmark_total_tokens_mean": 180.0,
                    "benchmark.raw_prompt_tokens_mean": 120.0,
                    "benchmark.raw_completion_tokens_mean": 60.0,
                },
            },
            {
                "id": "openclaw",
                "metrics": {
                    "cost.token_efficiency_score": 60.0,
                    "cost.token_efficiency_tokens_per_success_effective": 700.0,
                    "cost.token_efficiency_telemetry_coverage": 1.0,
                    "cost.benchmark_tokens_per_success": 700.0,
                    "cost.benchmark_total_tokens_mean": 300.0,
                    "benchmark.raw_prompt_tokens_mean": 180.0,
                    "benchmark.raw_completion_tokens_mean": 120.0,
                },
            },
        ],
        "metric_board": [
            {
                "metric": "cost.token_efficiency_score",
                "preference": "higher_is_better",
                "values": {"thomas": 82.0, "openclaw": 60.0},
                "participants": ["thomas", "openclaw"],
                "winners": ["thomas"],
            }
        ],
    }
    evaluation = contract.evaluate_test_suite_contract(
        contract=sample_contract,
        result=result,
        focus_agent="thomas",
        head_to_head_pair=["thomas", "openclaw"],
    )
    token_h2h = dict(dict(dict(evaluation["scores"]).get("token_efficiency") or {}).get("head_to_head") or {})
    assert bool(token_h2h.get("enabled")) is True
    assert int(token_h2h.get("counted_metrics") or 0) == 3
    assert float(token_h2h.get("agent_a_score") or 0.0) > float(token_h2h.get("agent_b_score") or 0.0)
