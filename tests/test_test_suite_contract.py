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
            {"id": "core.001", "category": "coverage_and_correctness", "title": "x", "implementation_state": "implemented"},
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
