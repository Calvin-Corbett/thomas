from __future__ import annotations

from thomas.plugins import benchmark_program as benchmark_program_plugin


def _base_metric_board() -> list[dict]:
    return [
        {
            "metric": "tests.files",
            "category": "test_rigor",
            "test_mode": "quick",
            "values": {"steady": 10, "noisy": 10, "override_case": 10},
            "winners": ["steady", "noisy", "override_case"],
        },
        {
            "metric": "performance.load.pass_rate",
            "category": "performance_load",
            "test_mode": "dynamic",
            "values": {"steady": 1.0, "noisy": 1.0, "override_case": 1.0},
            "winners": ["steady", "noisy", "override_case"],
        },
    ]


def _agent_metrics(*, weighted_stddev: float, success_stddev: float) -> dict:
    return {
        "tests.files": 10,
        "tests.loc": 20,
        "production.strict_checks.pass_rate": 1.0,
        "performance.load.pass_rate": 1.0,
        "resilience.probes.pass_rate": 1.0,
        "security.probes.pass_rate": 1.0,
        "cost.probes.pass_rate": 1.0,
        "benchmark.runs_count": 3,
        "integrity.python_syntax_errors": 0,
        "integrity.invalid_json_files": 0,
        "integrity.missing_required_paths": 0,
        "integrity.empty_production_asset_files": 0,
        "security.secret_like_hits": 0,
        "security.risky_construct_hits_count": 0,
        "benchmark.weighted_score_stddev": weighted_stddev,
        "benchmark.success_rate_stddev": success_stddev,
    }


def test_governance_thresholds_calibrate_from_measured_variance() -> None:
    contract = {
        "benchmark_program": {
            "id": "bp",
            "lane_weights": {"quick": 0.4, "dynamic": 0.6},
            "governance_calibration": {
                "enabled": True,
                "min_agent_samples": 2,
                "min_runs_count": 1,
                "reliability_quantile": 0.75,
                "reliability_margin": 0.01,
                "reliability_floor": 0.05,
                "reliability_ceiling": 0.4,
                "reproducibility_quantile": 0.5,
                "reproducibility_margin": 0.005,
                "reproducibility_floor": 0.03,
                "reproducibility_ceiling": 0.3,
            },
        },
        "benchmark_families": [],
        "catalog_checks": [],
    }
    result = {
        "suite": {"competitor_catalog_count": 1},
        "prediction_evo_scope": {},
        "metric_board": _base_metric_board(),
        "agents": [
            {"id": "steady", "metrics": _agent_metrics(weighted_stddev=0.06, success_stddev=0.06)},
            {"id": "noisy", "metrics": _agent_metrics(weighted_stddev=0.21, success_stddev=0.21)},
        ],
    }
    contract_eval = {
        "scores": {
            "agents": [
                {"agent": "steady", "token_efficiency_score": 70.0},
                {"agent": "noisy", "token_efficiency_score": 70.0},
            ]
        }
    }

    program = benchmark_program_plugin.evaluate_benchmark_program(
        contract=contract,
        result=result,
        contract_evaluation=contract_eval,
    )

    assert bool(program["governance_calibration"]["applied"]) is True
    thresholds = dict(program["governance_thresholds"])
    assert float(thresholds["reliability"]["weighted_stddev_max"]) < 0.25
    assert float(thresholds["reproducibility"]["weighted_stddev_max"]) < float(
        thresholds["reliability"]["weighted_stddev_max"]
    )

    rows = {str(row["agent"]): row for row in program["ranking"]}
    assert bool(rows["steady"]["governance_gates"]["reliability_gate"]) is True
    assert bool(rows["steady"]["governance_gates"]["reproducibility_gate"]) is True
    assert bool(rows["noisy"]["governance_gates"]["reliability_gate"]) is False
    assert bool(rows["noisy"]["governance_gates"]["reproducibility_gate"]) is False
    assert str(rows["steady"]["governance_verdict"]) == "GO"
    assert str(rows["noisy"]["governance_verdict"]) == "LIMITED_GO"


def test_governance_threshold_overrides_take_precedence_over_calibration() -> None:
    contract = {
        "benchmark_program": {
            "id": "bp",
            "lane_weights": {"quick": 0.4, "dynamic": 0.6},
            "governance_calibration": {
                "enabled": True,
                "min_agent_samples": 1,
                "reliability_quantile": 0.5,
                "reproducibility_quantile": 0.5,
                "reliability_margin": 0.0,
                "reproducibility_margin": 0.0,
                "reliability_floor": 0.05,
                "reliability_ceiling": 0.2,
                "reproducibility_floor": 0.03,
                "reproducibility_ceiling": 0.15,
            },
            "governance_thresholds": {
                "reliability": {"weighted_stddev_max": 0.3, "success_stddev_max": 0.3},
                "reproducibility": {"weighted_stddev_max": 0.3, "success_stddev_max": 0.3},
            },
        },
        "benchmark_families": [],
        "catalog_checks": [],
    }
    result = {
        "suite": {"competitor_catalog_count": 1},
        "prediction_evo_scope": {},
        "metric_board": _base_metric_board(),
        "agents": [
            {"id": "override_case", "metrics": _agent_metrics(weighted_stddev=0.27, success_stddev=0.27)},
        ],
    }
    contract_eval = {
        "scores": {
            "agents": [
                {"agent": "override_case", "token_efficiency_score": 70.0},
            ]
        }
    }

    program = benchmark_program_plugin.evaluate_benchmark_program(
        contract=contract,
        result=result,
        contract_evaluation=contract_eval,
    )

    thresholds = dict(program["governance_thresholds"])
    assert float(thresholds["reliability"]["weighted_stddev_max"]) == 0.3
    assert float(thresholds["reproducibility"]["weighted_stddev_max"]) == 0.3

    row = dict(program["ranking"][0])
    gates = dict(row["governance_gates"])
    assert bool(gates["reliability_gate"]) is True
    assert bool(gates["reproducibility_gate"]) is True
    assert str(row["governance_verdict"]) == "GO"
