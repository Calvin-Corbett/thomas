from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any


def _safe_float(value: Any) -> float | None:
    try:
        num = float(value)
    except Exception:
        return None
    if num != num or num in {float("inf"), float("-inf")}:
        return None
    return num


def _is_number(value: Any) -> bool:
    return _safe_float(value) is not None


def _safe_ratio(numerator: float | int, denominator: float | int) -> float:
    if float(denominator) <= 0:
        return 0.0
    return float(numerator) / float(denominator)


def _clamp(value: float, lower: float, upper: float) -> float:
    if lower > upper:
        lower, upper = upper, lower
    return min(max(float(value), float(lower)), float(upper))


def _quantile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(item) for item in values)
    if len(ordered) == 1:
        return float(ordered[0])
    q = _clamp(float(quantile), 0.0, 1.0)
    idx = (len(ordered) - 1) * q
    lo = int(idx)
    hi = min(lo + 1, len(ordered) - 1)
    frac = idx - lo
    return float(ordered[lo] * (1.0 - frac) + ordered[hi] * frac)


def _default_governance_thresholds() -> dict[str, float]:
    return {
        "correctness.dynamic_score_min": 70.0,
        "correctness.quick_score_min": 75.0,
        "reliability.resilience_pass_rate_min": 0.95,
        "reliability.weighted_stddev_max": 0.25,
        "reliability.success_stddev_max": 0.25,
        "reproducibility.weighted_stddev_max": 0.1,
        "reproducibility.success_stddev_max": 0.1,
        "capability.go_min": 85.0,
        "capability.limited_go_min": 60.0,
        "capability.limited_go_required_gate_count": 3.0,
    }


def _governance_threshold_payload(thresholds: Mapping[str, float]) -> dict[str, Any]:
    return {
        "correctness": {
            "dynamic_score_min": round(float(thresholds.get("correctness.dynamic_score_min", 70.0)), 6),
            "quick_score_min": round(float(thresholds.get("correctness.quick_score_min", 75.0)), 6),
        },
        "reliability": {
            "resilience_pass_rate_min": round(float(thresholds.get("reliability.resilience_pass_rate_min", 0.95)), 6),
            "weighted_stddev_max": round(float(thresholds.get("reliability.weighted_stddev_max", 0.25)), 6),
            "success_stddev_max": round(float(thresholds.get("reliability.success_stddev_max", 0.25)), 6),
        },
        "reproducibility": {
            "weighted_stddev_max": round(float(thresholds.get("reproducibility.weighted_stddev_max", 0.1)), 6),
            "success_stddev_max": round(float(thresholds.get("reproducibility.success_stddev_max", 0.1)), 6),
        },
        "capability": {
            "go_min": round(float(thresholds.get("capability.go_min", 85.0)), 6),
            "limited_go_min": round(float(thresholds.get("capability.limited_go_min", 60.0)), 6),
            "limited_go_required_gate_count": int(
                max(1, round(float(thresholds.get("capability.limited_go_required_gate_count", 3.0))))
            ),
        },
    }


def _apply_governance_overrides(
    *,
    thresholds: dict[str, float],
    program_cfg: Mapping[str, Any],
) -> dict[str, bool]:
    overridden = {key: False for key in thresholds}
    section = dict(program_cfg.get("governance_thresholds") or {})
    correctness = dict(section.get("correctness") or {})
    reliability = dict(section.get("reliability") or {})
    reproducibility = dict(section.get("reproducibility") or {})
    capability = dict(section.get("capability") or {})

    def _set(key: str, raw: Any) -> None:
        value = _safe_float(raw)
        if value is None:
            return
        thresholds[key] = float(value)
        overridden[key] = True

    _set("correctness.dynamic_score_min", correctness.get("dynamic_score_min"))
    _set("correctness.dynamic_score_min", correctness.get("dynamic_min"))
    _set("correctness.quick_score_min", correctness.get("quick_score_min"))
    _set("correctness.quick_score_min", correctness.get("quick_min"))

    _set("reliability.resilience_pass_rate_min", reliability.get("resilience_pass_rate_min"))
    _set("reliability.weighted_stddev_max", reliability.get("weighted_stddev_max"))
    _set("reliability.weighted_stddev_max", reliability.get("max_weighted_stddev"))
    _set("reliability.success_stddev_max", reliability.get("success_stddev_max"))
    _set("reliability.success_stddev_max", reliability.get("max_success_stddev"))

    _set("reproducibility.weighted_stddev_max", reproducibility.get("weighted_stddev_max"))
    _set("reproducibility.weighted_stddev_max", reproducibility.get("max_weighted_stddev"))
    _set("reproducibility.success_stddev_max", reproducibility.get("success_stddev_max"))
    _set("reproducibility.success_stddev_max", reproducibility.get("max_success_stddev"))

    _set("capability.go_min", capability.get("go_min"))
    _set("capability.go_min", capability.get("go_capability_min"))
    _set("capability.limited_go_min", capability.get("limited_go_min"))
    _set("capability.limited_go_min", capability.get("limited_go_capability_min"))
    _set("capability.limited_go_required_gate_count", capability.get("limited_go_required_gate_count"))
    _set("capability.limited_go_required_gate_count", capability.get("limited_go_min_passed_gates"))

    _set("correctness.dynamic_score_min", section.get("dynamic_score_min"))
    _set("correctness.quick_score_min", section.get("quick_score_min"))
    _set("reliability.resilience_pass_rate_min", section.get("resilience_pass_rate_min"))
    _set("reliability.weighted_stddev_max", section.get("reliability_weighted_stddev_max"))
    _set("reliability.success_stddev_max", section.get("reliability_success_stddev_max"))
    _set("reproducibility.weighted_stddev_max", section.get("reproducibility_weighted_stddev_max"))
    _set("reproducibility.success_stddev_max", section.get("reproducibility_success_stddev_max"))
    _set("capability.go_min", section.get("go_capability_min"))
    _set("capability.limited_go_min", section.get("limited_go_capability_min"))
    _set("capability.limited_go_required_gate_count", section.get("limited_go_min_passed_gates"))

    return overridden


def _derive_governance_thresholds(
    *,
    program_cfg: Mapping[str, Any],
    agents: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, float], dict[str, Any]]:
    thresholds = _default_governance_thresholds()
    calibration_cfg = dict(program_cfg.get("governance_calibration") or {})
    enabled = bool(calibration_cfg.get("enabled", True))
    min_samples = int(max(1, round(float(_safe_float(calibration_cfg.get("min_agent_samples")) or 2.0))))
    min_runs = float(_safe_float(calibration_cfg.get("min_runs_count")) or 1.0)

    weighted_samples: list[float] = []
    success_samples: list[float] = []
    for row in agents:
        metrics = dict(row.get("metrics") or {})
        runs_count = _safe_float(metrics.get("benchmark.runs_count"))
        if runs_count is not None and runs_count < min_runs:
            continue
        weighted = _safe_float(metrics.get("benchmark.weighted_score_stddev"))
        success = _safe_float(metrics.get("benchmark.success_rate_stddev"))
        if weighted is not None:
            weighted_samples.append(float(weighted))
        if success is not None:
            success_samples.append(float(success))

    applied = False
    if enabled and (len(weighted_samples) >= min_samples or len(success_samples) >= min_samples):
        reliability_quantile = float(_safe_float(calibration_cfg.get("reliability_quantile")) or 0.75)
        reproducibility_quantile = float(_safe_float(calibration_cfg.get("reproducibility_quantile")) or 0.5)
        reliability_margin = max(0.0, float(_safe_float(calibration_cfg.get("reliability_margin")) or 0.05))
        reproducibility_margin = max(0.0, float(_safe_float(calibration_cfg.get("reproducibility_margin")) or 0.02))
        reliability_floor = float(_safe_float(calibration_cfg.get("reliability_floor")) or 0.08)
        reliability_ceiling = float(_safe_float(calibration_cfg.get("reliability_ceiling")) or 0.4)
        reproducibility_floor = float(_safe_float(calibration_cfg.get("reproducibility_floor")) or 0.04)
        reproducibility_ceiling = float(_safe_float(calibration_cfg.get("reproducibility_ceiling")) or 0.25)

        rel_weighted = _quantile(weighted_samples, reliability_quantile)
        rel_success = _quantile(success_samples, reliability_quantile)
        repro_weighted = _quantile(weighted_samples, reproducibility_quantile)
        repro_success = _quantile(success_samples, reproducibility_quantile)

        if rel_weighted is not None:
            thresholds["reliability.weighted_stddev_max"] = _clamp(
                float(rel_weighted) + reliability_margin,
                reliability_floor,
                reliability_ceiling,
            )
            applied = True
        if rel_success is not None:
            thresholds["reliability.success_stddev_max"] = _clamp(
                float(rel_success) + reliability_margin,
                reliability_floor,
                reliability_ceiling,
            )
            applied = True
        if repro_weighted is not None:
            thresholds["reproducibility.weighted_stddev_max"] = _clamp(
                float(repro_weighted) + reproducibility_margin,
                reproducibility_floor,
                reproducibility_ceiling,
            )
            applied = True
        if repro_success is not None:
            thresholds["reproducibility.success_stddev_max"] = _clamp(
                float(repro_success) + reproducibility_margin,
                reproducibility_floor,
                reproducibility_ceiling,
            )
            applied = True

    overridden = _apply_governance_overrides(thresholds=thresholds, program_cfg=program_cfg)

    if not overridden.get("reproducibility.weighted_stddev_max", False):
        thresholds["reproducibility.weighted_stddev_max"] = min(
            float(thresholds["reproducibility.weighted_stddev_max"]),
            float(thresholds["reliability.weighted_stddev_max"]),
        )
    if not overridden.get("reproducibility.success_stddev_max", False):
        thresholds["reproducibility.success_stddev_max"] = min(
            float(thresholds["reproducibility.success_stddev_max"]),
            float(thresholds["reliability.success_stddev_max"]),
        )

    threshold_payload = _governance_threshold_payload(thresholds)
    calibration = {
        "enabled": bool(enabled),
        "applied": bool(applied),
        "sample_counts": {
            "weighted_score_stddev": int(len(weighted_samples)),
            "success_rate_stddev": int(len(success_samples)),
        },
        "min_agent_samples": int(min_samples),
        "min_runs_count": float(min_runs),
        "overrides_applied": sorted(key for key, is_overridden in overridden.items() if bool(is_overridden)),
        "thresholds": threshold_payload,
    }
    return thresholds, calibration


def _default_test_mode_for_category(category: str) -> str:
    dynamic_categories = {
        "agent_runtime",
        "agentic_native",
        "browser_and_operator_ux",
        "performance_and_cost",
        "reliability_and_release_ops",
        "security_depth",
        "compliance_and_competitive_intel",
        "task_quality",
        "safety_and_policy",
        "evaluation_governance",
        "release_decisioning",
    }
    human_categories = {"human_quality"}
    text = str(category or "").strip().lower()
    if text in human_categories:
        return "human"
    if text in dynamic_categories:
        return "dynamic"
    return "quick"


def _runtime_test_mode(metric_row: Mapping[str, Any]) -> str:
    explicit = str(metric_row.get("test_mode") or "").strip().lower()
    if explicit in {"quick", "dynamic", "human"}:
        return explicit
    category = str(metric_row.get("category") or "").strip().lower()
    return _default_test_mode_for_category(category)


def _agent_category_signals(
    *,
    metrics: Mapping[str, Any],
    suite: Mapping[str, Any],
    prediction: Mapping[str, Any],
) -> dict[str, bool]:
    tests_files = _safe_float(metrics.get("tests.files")) or 0.0
    tests_loc = _safe_float(metrics.get("tests.loc")) or 0.0
    cli_top = _safe_float(metrics.get("cli.top_level_commands")) or 0.0
    browser_files = _safe_float(metrics.get("browser.files")) or 0.0
    extensions_dirs = _safe_float(metrics.get("extensions.directories")) or 0.0
    gateway_chat = _safe_float(metrics.get("gateway.openai_chat_completions.files")) or 0.0
    gateway_resp = _safe_float(metrics.get("gateway.responses.files")) or 0.0

    strict_pass = _safe_float(metrics.get("production.strict_checks.pass_rate"))
    perf_pass = _safe_float(metrics.get("performance.load.pass_rate"))
    res_pass = _safe_float(metrics.get("resilience.probes.pass_rate"))
    sec_pass = _safe_float(metrics.get("security.probes.pass_rate"))
    cost_pass = _safe_float(metrics.get("cost.probes.pass_rate"))
    bench_runs = _safe_float(metrics.get("benchmark.runs_count")) or 0.0

    syntax_errors = _safe_float(metrics.get("integrity.python_syntax_errors")) or 0.0
    invalid_json = _safe_float(metrics.get("integrity.invalid_json_files")) or 0.0
    missing_required = _safe_float(metrics.get("integrity.missing_required_paths")) or 0.0
    empty_assets = _safe_float(metrics.get("integrity.empty_production_asset_files")) or 0.0

    competitor_catalog_count = int(_safe_float(suite.get("competitor_catalog_count")) or 0)

    has_tests = tests_files > 0 and tests_loc > 0
    integrity_ok = syntax_errors <= 0 and invalid_json <= 0 and missing_required <= 0 and empty_assets <= 0
    cli_surface = cli_top > 0
    gateway_surface = gateway_chat > 0 or gateway_resp > 0
    browser_surface = browser_files > 0
    extensions_surface = extensions_dirs > 0

    strict_ok = strict_pass is not None and strict_pass >= 1.0
    perf_ok = perf_pass is not None and perf_pass >= 1.0
    res_ok = res_pass is not None and res_pass >= 1.0
    sec_ok = sec_pass is not None and sec_pass >= 1.0
    cost_ok = cost_pass is not None and cost_pass >= 1.0
    benchmark_ok = bench_runs > 0

    competitor_ok = competitor_catalog_count > 0
    prediction_ok = isinstance(prediction, dict)

    return {
        "coverage_and_correctness": bool(has_tests and integrity_ok),
        "interfaces_and_protocols": bool(cli_surface and gateway_surface),
        "agent_runtime": bool(benchmark_ok and res_ok and sec_ok),
        "browser_and_operator_ux": bool(browser_surface),
        "extensions_and_state": bool(extensions_surface and integrity_ok),
        "security_depth": bool(sec_ok and integrity_ok),
        "performance_and_cost": bool(perf_ok and cost_ok),
        "reliability_and_release_ops": bool(strict_ok and benchmark_ok),
        "compliance_and_competitive_intel": bool(competitor_ok and prediction_ok),
        "agentic_native": bool(strict_ok and benchmark_ok and res_ok and sec_ok and cost_ok),
    }


def _evaluate_catalog_check(
    *,
    raw: Mapping[str, Any],
    category_signals: Mapping[str, bool],
    evidence_checks: Mapping[str, Any],
) -> dict[str, Any]:
    rid = str(raw.get("id") or "").strip()
    category = str(raw.get("category") or "uncategorized").strip()
    mode = str(raw.get("test_mode") or _default_test_mode_for_category(category)).strip().lower() or "quick"
    family = str(raw.get("benchmark_family") or category).strip()
    implementation_mode = str(raw.get("implementation_mode") or "contract_rule_v1").strip().lower()
    pass_score_gte = _safe_float(raw.get("pass_score_gte"))
    if pass_score_gte is None:
        pass_score_gte = 100.0

    passed = False
    evidence_found = False
    evidence_score = None
    evidence_pass = None
    if implementation_mode in {"evidence_required", "evidence_required_v1"}:
        evidence_id = str(raw.get("evidence_id") or rid).strip()
        evidence = dict(evidence_checks.get(evidence_id) or {})
        evidence_found = bool(evidence)
        if evidence_found:
            if isinstance(evidence.get("pass"), bool):
                evidence_pass = bool(evidence.get("pass"))
            evidence_score = _safe_float(evidence.get("score"))
            if evidence_pass is None and evidence_score is not None:
                evidence_pass = bool(evidence_score >= float(pass_score_gte))
            passed = bool(evidence_pass is True)
    else:
        passed = bool(category_signals.get(category, False))

    return {
        "id": rid,
        "category": category,
        "test_mode": mode,
        "benchmark_family": family,
        "implementation_mode": implementation_mode,
        "passed": bool(passed),
        "evidence_found": bool(evidence_found),
        "evidence_score": evidence_score,
        "evidence_pass": evidence_pass,
    }


def _build_go_verdict(
    *,
    metrics: Mapping[str, Any],
    dynamic_score: float,
    quick_score: float,
    capability_score: float,
    token_efficiency_score: float | None,
    governance_thresholds: Mapping[str, float],
) -> dict[str, Any]:
    sec_probe = _safe_float(metrics.get("security.probes.pass_rate"))
    sec_secret_hits = _safe_float(metrics.get("security.secret_like_hits"))
    sec_risky_hits = _safe_float(metrics.get("security.risky_construct_hits_count"))
    res_probe = _safe_float(metrics.get("resilience.probes.pass_rate"))
    cost_probe = _safe_float(metrics.get("cost.probes.pass_rate"))
    weighted_stddev = _safe_float(metrics.get("benchmark.weighted_score_stddev"))
    success_stddev = _safe_float(metrics.get("benchmark.success_rate_stddev"))
    defaults = _default_governance_thresholds()
    dynamic_min = float(
        governance_thresholds.get("correctness.dynamic_score_min", defaults["correctness.dynamic_score_min"])
    )
    quick_min = float(governance_thresholds.get("correctness.quick_score_min", defaults["correctness.quick_score_min"]))
    reliability_resilience_min = float(
        governance_thresholds.get(
            "reliability.resilience_pass_rate_min",
            defaults["reliability.resilience_pass_rate_min"],
        )
    )
    reliability_weighted_max = float(
        governance_thresholds.get(
            "reliability.weighted_stddev_max",
            defaults["reliability.weighted_stddev_max"],
        )
    )
    reliability_success_max = float(
        governance_thresholds.get(
            "reliability.success_stddev_max",
            defaults["reliability.success_stddev_max"],
        )
    )
    reproducibility_weighted_max = float(
        governance_thresholds.get(
            "reproducibility.weighted_stddev_max",
            defaults["reproducibility.weighted_stddev_max"],
        )
    )
    reproducibility_success_max = float(
        governance_thresholds.get(
            "reproducibility.success_stddev_max",
            defaults["reproducibility.success_stddev_max"],
        )
    )
    go_capability_min = float(governance_thresholds.get("capability.go_min", defaults["capability.go_min"]))
    limited_go_capability_min = float(
        governance_thresholds.get("capability.limited_go_min", defaults["capability.limited_go_min"])
    )

    safety_gate = bool(
        (sec_probe is not None and sec_probe >= 1.0)
        and (sec_secret_hits is not None and sec_secret_hits <= 0.0)
        and (sec_risky_hits is not None and sec_risky_hits <= 0.0)
    )
    correctness_gate = bool(dynamic_score >= dynamic_min and quick_score >= quick_min)
    reliability_gate = bool(
        (res_probe is not None and res_probe >= reliability_resilience_min)
        and (weighted_stddev is not None and weighted_stddev <= reliability_weighted_max)
        and (success_stddev is not None and success_stddev <= reliability_success_max)
    )
    cost_gate = bool((cost_probe is not None and cost_probe >= 1.0) and (token_efficiency_score is not None))
    reproducibility_gate = bool(
        (weighted_stddev is not None and weighted_stddev <= reproducibility_weighted_max)
        and (success_stddev is not None and success_stddev <= reproducibility_success_max)
    )
    gates = {
        "safety_gate": safety_gate,
        "real_task_correctness_gate": correctness_gate,
        "reliability_gate": reliability_gate,
        "cost_token_gate": cost_gate,
        "reproducibility_gate": reproducibility_gate,
    }
    passed = sum(1 for value in gates.values() if bool(value))
    limited_go_min_passed = int(
        max(
            1,
            round(
                float(
                    governance_thresholds.get(
                        "capability.limited_go_required_gate_count",
                        defaults["capability.limited_go_required_gate_count"],
                    )
                )
            ),
        )
    )
    limited_go_min_passed = min(limited_go_min_passed, len(gates))
    if all(bool(value) for value in gates.values()) and capability_score >= go_capability_min:
        verdict = "GO"
    elif safety_gate and passed >= limited_go_min_passed and capability_score >= limited_go_capability_min:
        verdict = "LIMITED_GO"
    else:
        verdict = "NO_GO"
    return {"verdict": verdict, "gates": gates, "passed_gates": int(passed), "total_gates": int(len(gates))}


def evaluate_benchmark_program(
    *,
    contract: Mapping[str, Any],
    result: Mapping[str, Any],
    contract_evaluation: Mapping[str, Any],
) -> dict[str, Any]:
    suite = dict(result.get("suite") or {})
    prediction = dict(result.get("prediction_evo_scope") or {})
    runtime_rows = [row for row in list(result.get("metric_board") or []) if isinstance(row, dict)]
    catalog_checks = [row for row in list(contract.get("catalog_checks") or []) if isinstance(row, dict)]
    agents = [row for row in list(result.get("agents") or []) if isinstance(row, dict)]
    [str(row.get("id") or "").strip() for row in agents if str(row.get("id") or "").strip()]

    token_score_map = {
        str(row.get("agent") or "").strip(): _safe_float(row.get("token_efficiency_score"))
        for row in list(dict(contract_evaluation.get("scores") or {}).get("agents") or [])
        if str(row.get("agent") or "").strip()
    }

    program_cfg = dict(contract.get("benchmark_program") or {})
    contract_family_rows = [row for row in list(contract.get("benchmark_families") or []) if isinstance(row, dict)]
    family_catalog = {
        str(row.get("id") or "").strip(): dict(row) for row in contract_family_rows if str(row.get("id") or "").strip()
    }
    lane_weights = dict(program_cfg.get("lane_weights") or {"quick": 0.35, "dynamic": 0.5, "human": 0.15})
    lane_weights = {
        str(k).strip().lower(): float(v) for k, v in lane_weights.items() if str(k).strip() and _is_number(v)
    }
    if not lane_weights:
        lane_weights = {"quick": 0.35, "dynamic": 0.5, "human": 0.15}
    weight_total = sum(lane_weights.values()) or 1.0
    governance_thresholds, governance_calibration = _derive_governance_thresholds(
        program_cfg=program_cfg,
        agents=agents,
    )

    rows: list[dict[str, Any]] = []
    for agent in agents:
        aid = str(agent.get("id") or "").strip()
        metrics = dict(agent.get("metrics") or {})
        evidence = dict(dict(agent.get("benchmark_evidence") or {}).get("checks") or {})
        category_signals = _agent_category_signals(metrics=metrics, suite=suite, prediction=prediction)
        lane_possible = Counter()
        lane_passed = Counter()
        family_possible = Counter()
        family_passed = Counter()

        for metric_row in runtime_rows:
            mode = _runtime_test_mode(metric_row)
            lane_possible[mode] += 1
            winners = set(str(item).strip() for item in (metric_row.get("winners") or []) if str(item).strip())
            if aid in winners:
                lane_passed[mode] += 1

        catalog_evaluated: list[dict[str, Any]] = []
        for check in catalog_checks:
            evaluated = _evaluate_catalog_check(raw=check, category_signals=category_signals, evidence_checks=evidence)
            catalog_evaluated.append(evaluated)
            mode = str(evaluated.get("test_mode") or "quick")
            family = str(evaluated.get("benchmark_family") or "uncategorized")
            lane_possible[mode] += 1
            family_possible[family] += 1
            if bool(evaluated.get("passed")):
                lane_passed[mode] += 1
                family_passed[family] += 1

        lane_scores: dict[str, dict[str, Any]] = {}
        for lane in sorted(set(list(lane_possible.keys()) + list(lane_weights.keys()))):
            possible = int(lane_possible.get(lane) or 0)
            passed = int(lane_passed.get(lane) or 0)
            lane_scores[lane] = {
                "possible": possible,
                "passed": passed,
                "score": round(_safe_ratio(passed, possible) * 100.0, 3) if possible > 0 else 0.0,
                "weight": round(float(lane_weights.get(lane) or 0.0), 6),
            }

        capability_score = round(
            sum(
                float(dict(lane_scores.get(lane) or {}).get("score") or 0.0) * float(weight)
                for lane, weight in lane_weights.items()
            )
            / float(weight_total),
            3,
        )
        quick_score = float(dict(lane_scores.get("quick") or {}).get("score") or 0.0)
        dynamic_score = float(dict(lane_scores.get("dynamic") or {}).get("score") or 0.0)
        verdict = _build_go_verdict(
            metrics=metrics,
            dynamic_score=dynamic_score,
            quick_score=quick_score,
            capability_score=float(capability_score),
            token_efficiency_score=token_score_map.get(aid),
            governance_thresholds=governance_thresholds,
        )
        family_scores = {}
        for family in sorted(family_possible.keys()):
            possible = int(family_possible.get(family) or 0)
            passed = int(family_passed.get(family) or 0)
            profile = dict(family_catalog.get(family) or {})
            family_scores[family] = {
                "name": str(profile.get("name") or family.replace("_", " ").title()),
                "default_test_mode": str(profile.get("default_test_mode") or _default_test_mode_for_category(family)),
                "description": str(profile.get("description") or ""),
                "possible": possible,
                "passed": passed,
                "score": round(_safe_ratio(passed, possible) * 100.0, 3) if possible > 0 else 0.0,
            }
        rows.append(
            {
                "agent": aid,
                "overall_benchmark_capability_score": float(capability_score),
                "lane_scores": lane_scores,
                "family_scores": family_scores,
                "governance_verdict": str(verdict.get("verdict") or "NO_GO"),
                "governance_gates": dict(verdict.get("gates") or {}),
                "catalog_checks": {
                    "possible": int(len(catalog_evaluated)),
                    "passed": int(sum(1 for row in catalog_evaluated if bool(row.get("passed")))),
                },
            }
        )

    ranking = sorted(
        list(rows), key=lambda row: float(row.get("overall_benchmark_capability_score") or 0.0), reverse=True
    )
    for idx, row in enumerate(ranking, start=1):
        row["rank"] = int(idx)
    verdict_counts = Counter(str(row.get("governance_verdict") or "NO_GO") for row in rows)
    return {
        "id": str(program_cfg.get("id") or "thomas-professional-benchmark-v2"),
        "lane_weights": {k: round(float(v), 6) for k, v in lane_weights.items()},
        "family_catalog": [family_catalog[key] for key in sorted(family_catalog.keys())],
        "methodology": {
            "lanes": "quick and dynamic lanes are scored independently and weighted into one capability score",
            "overall_benchmark_capability_score": "weighted average of lane scores where unmet checks count against score",
            "governance_verdict": "GO requires all hard gates; LIMITED_GO requires safety + configured gate count; otherwise NO_GO",
            "governance_thresholds": "reliability/reproducibility stddev gates are calibrated from measured benchmark variance when sufficient samples exist",
        },
        "governance_thresholds": _governance_threshold_payload(governance_thresholds),
        "governance_calibration": governance_calibration,
        "runtime_metric_count": int(len(runtime_rows)),
        "catalog_check_count": int(len(catalog_checks)),
        "verdict_counts": dict(verdict_counts),
        "ranking": ranking,
    }
