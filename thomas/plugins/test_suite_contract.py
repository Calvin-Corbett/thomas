from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

DEFAULT_TEST_MODES = ("quick", "dynamic", "human")

DYNAMIC_CATEGORIES = {
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

HUMAN_CATEGORIES = {"human_quality"}


def load_test_suite_contract(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "id": "missing",
            "version": 1,
            "runtime_metric_contract": {"include_all_runtime_metrics": True},
            "catalog_checks": [],
            "errors": [f"missing contract: {path}"],
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "id": "invalid",
            "version": 1,
            "runtime_metric_contract": {"include_all_runtime_metrics": True},
            "catalog_checks": [],
            "errors": [f"invalid contract JSON ({path}): {type(exc).__name__}: {exc}"],
        }
    if not isinstance(payload, dict):
        return {
            "id": "invalid_shape",
            "version": 1,
            "runtime_metric_contract": {"include_all_runtime_metrics": True},
            "catalog_checks": [],
            "errors": [f"contract must be a JSON object: {path}"],
        }
    out = dict(payload)
    out.setdefault("id", path.stem)
    out.setdefault("version", 1)
    out.setdefault("runtime_metric_contract", {"include_all_runtime_metrics": True})
    out.setdefault("catalog_checks", [])
    out.setdefault("errors", [])
    return out


def _is_number(value: Any) -> bool:
    try:
        num = float(value)
    except Exception:
        return False
    return num == num and num not in {float("inf"), float("-inf")}


def _iter_runtime_metric_rows(result: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    for row in list(result.get("metric_board") or []):
        if isinstance(row, dict):
            yield row


def _safe_float(value: Any) -> float | None:
    try:
        num = float(value)
    except Exception:
        return None
    if num != num or num in {float("inf"), float("-inf")}:
        return None
    return num


def _agent_metrics(result: Mapping[str, Any], agent_id: str) -> dict[str, Any]:
    aid = str(agent_id or "").strip()
    for row in list(result.get("agents") or []):
        if not isinstance(row, dict):
            continue
        if str(row.get("id") or "").strip() != aid:
            continue
        return dict(row.get("metrics") or {})
    return {}


def _check_signals(result: Mapping[str, Any], agent_id: str) -> dict[str, bool]:
    metrics = _agent_metrics(result, agent_id)
    suite = dict(result.get("suite") or {})
    focus = dict(result.get("focus") or {})
    prediction = dict(result.get("prediction_evo_scope") or {})

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


def _pairwise_scalar_outcome(left_value: Any, right_value: Any, *, preference: str) -> str | None:
    left_has = _is_number(left_value)
    right_has = _is_number(right_value)
    if not left_has and not right_has:
        return None
    if left_has and not right_has:
        return "left"
    if right_has and not left_has:
        return "right"
    lv = float(left_value)
    rv = float(right_value)
    if abs(lv - rv) <= 1e-9:
        return "tie"
    pref = str(preference or "higher_is_better").strip().lower()
    if pref == "lower_is_better":
        return "left" if lv < rv else "right"
    return "left" if lv > rv else "right"


def _safe_ratio(numerator: float | int, denominator: float | int) -> float:
    if float(denominator) <= 0:
        return 0.0
    return float(numerator) / float(denominator)


def _default_test_mode_for_category(category: Any) -> str:
    text = str(category or "").strip().lower()
    if text in HUMAN_CATEGORIES:
        return "human"
    if text in DYNAMIC_CATEGORIES:
        return "dynamic"
    return "quick"


def _normalize_test_mode(mode: Any, *, category: Any = "") -> str:
    text = str(mode or "").strip().lower()
    if text in {"quick", "dynamic", "human"}:
        return text
    return _default_test_mode_for_category(category)


def _build_token_efficiency_row(result: Mapping[str, Any], agent_id: str) -> dict[str, Any]:
    metrics = _agent_metrics(result, agent_id)
    score = _safe_float(metrics.get("cost.token_efficiency_score"))
    effective_tokens = _safe_float(metrics.get("cost.token_efficiency_tokens_per_success_effective"))
    coverage = _safe_float(metrics.get("cost.token_efficiency_telemetry_coverage"))
    direct_tokens_per_success = _safe_float(metrics.get("cost.benchmark_tokens_per_success"))
    total_tokens_mean = _safe_float(metrics.get("cost.benchmark_total_tokens_mean"))
    prompt_tokens_mean = _safe_float(metrics.get("benchmark.raw_prompt_tokens_mean"))
    completion_tokens_mean = _safe_float(metrics.get("benchmark.raw_completion_tokens_mean"))
    success_rate = _safe_float(metrics.get("benchmark.raw_success_rate_mean"))
    if success_rate is None:
        success_rate = _safe_float(metrics.get("benchmark.success_rate_mean"))

    token_signals = [
        direct_tokens_per_success if direct_tokens_per_success is not None and direct_tokens_per_success > 0 else None,
        total_tokens_mean if total_tokens_mean is not None and total_tokens_mean > 0 else None,
        prompt_tokens_mean if prompt_tokens_mean is not None and prompt_tokens_mean > 0 else None,
        completion_tokens_mean if completion_tokens_mean is not None and completion_tokens_mean > 0 else None,
    ]
    token_signal_count = sum(1 for value in token_signals if value is not None)
    token_signal_total = len(token_signals)
    if coverage is None:
        coverage = _safe_ratio(token_signal_count, token_signal_total)
    coverage = max(0.0, min(1.0, float(coverage)))

    derived_source = ""
    if effective_tokens is None:
        if direct_tokens_per_success is not None and direct_tokens_per_success > 0:
            effective_tokens = float(direct_tokens_per_success)
            derived_source = "direct_tokens_per_success"
        elif total_tokens_mean is not None and total_tokens_mean > 0 and success_rate is not None and success_rate > 0:
            effective_tokens = float(total_tokens_mean) / max(float(success_rate), 0.05)
            derived_source = "derived_total_tokens_mean_div_success_rate"
        elif total_tokens_mean is not None and total_tokens_mean > 0:
            effective_tokens = float(total_tokens_mean)
            derived_source = "fallback_total_tokens_mean"
    else:
        derived_source = "agent_metric"

    if score is None and effective_tokens is not None and effective_tokens > 0:
        base = 100.0 / (1.0 + (float(effective_tokens) / 1500.0))
        score = float(base) * (0.65 + (0.35 * float(coverage)))

    has_token_evidence = token_signal_count > 0 or (effective_tokens is not None and effective_tokens > 0)
    return {
        "agent": str(agent_id),
        "token_efficiency_score": (round(float(score), 6) if score is not None else None),
        "effective_tokens_per_success": (round(float(effective_tokens), 6) if effective_tokens is not None else None),
        "telemetry_coverage": round(float(coverage), 6),
        "token_signal_count": int(token_signal_count),
        "token_signal_total": int(token_signal_total),
        "has_token_evidence": bool(has_token_evidence),
        "source": derived_source,
    }


def evaluate_test_suite_contract(
    *,
    contract: Mapping[str, Any],
    result: Mapping[str, Any],
    focus_agent: str,
    head_to_head_pair: Sequence[str] | None = None,
) -> dict[str, Any]:
    focus = str(focus_agent or "").strip()
    suite_cfg = dict(result.get("suite") or {})
    tie_policy = str(suite_cfg.get("head_to_head_tie_policy") or "half_point").strip().lower()
    if tie_policy not in {"half_point", "exclude"}:
        tie_policy = "half_point"
    runtime_metric_ids: list[str] = []
    runtime_metrics_with_focus_data = 0
    runtime_metrics_comparable = 0
    runtime_metrics_by_mode_total: Counter[str] = Counter()
    runtime_metrics_by_mode_with_focus_data: Counter[str] = Counter()
    runtime_metrics_by_mode_comparable: Counter[str] = Counter()
    for row in _iter_runtime_metric_rows(result):
        metric = str(row.get("metric") or "").strip()
        if not metric:
            continue
        runtime_metric_ids.append(metric)
        mode = _normalize_test_mode(row.get("test_mode"), category=row.get("category"))
        runtime_metrics_by_mode_total[mode] += 1
        values = dict(row.get("values") or {})
        if _is_number(values.get(focus)):
            runtime_metrics_with_focus_data += 1
            runtime_metrics_by_mode_with_focus_data[mode] += 1
        participants = list(row.get("participants") or [])
        if len(participants) >= 2:
            runtime_metrics_comparable += 1
            runtime_metrics_by_mode_comparable[mode] += 1

    catalog_checks_raw = [row for row in list(contract.get("catalog_checks") or []) if isinstance(row, dict)]

    def _build_catalog_rows_for_agent(agent_id: str) -> list[dict[str, Any]]:
        category_signals = _check_signals(result, agent_id)
        rows: list[dict[str, Any]] = []
        for raw in catalog_checks_raw:
            rid = str(raw.get("id") or "").strip()
            if not rid:
                continue
            state = str(raw.get("implementation_state") or "planned").strip().lower()
            category = str(raw.get("category") or "uncategorized").strip()
            mode = _normalize_test_mode(raw.get("test_mode"), category=category)
            title = str(raw.get("title") or rid).strip()
            applicable = category in category_signals
            passed = bool(category_signals.get(category, False)) if applicable else False
            rows.append(
                {
                    "id": rid,
                    "category": category,
                    "test_mode": mode,
                    "title": title,
                    "implementation_state": state,
                    "priority": str(raw.get("priority") or "p2").strip().lower(),
                    "description": str(raw.get("description") or "").strip(),
                    "rule_id": f"category_signal.{category}",
                    "applicable": bool(applicable),
                    "evaluated_pass": bool(passed),
                }
            )
        return rows

    catalog_rows = _build_catalog_rows_for_agent(focus)

    by_state = Counter(row["implementation_state"] for row in catalog_rows)
    by_eval = Counter("pass" if bool(row.get("evaluated_pass")) else "fail" for row in catalog_rows)
    by_category = Counter(row["category"] for row in catalog_rows)
    by_mode = Counter(_normalize_test_mode(row.get("test_mode"), category=row.get("category")) for row in catalog_rows)
    runtime_total = len(runtime_metric_ids)
    catalog_total = len(catalog_rows)
    implemented_catalog = int(catalog_total)
    catalog_passed = int(by_eval.get("pass", 0))
    catalog_failed = int(by_eval.get("fail", 0))
    tracked_total = runtime_total + catalog_total
    implemented_total = runtime_total + implemented_catalog

    agent_ids = [
        str(row.get("id") or "").strip()
        for row in list(result.get("agents") or [])
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    ]

    def _pairwise_metric_outcome(row: Mapping[str, Any], left: str, right: str) -> str | None:
        values = dict(row.get("values") or {})
        left_has = _is_number(values.get(left))
        right_has = _is_number(values.get(right))
        if not left_has and not right_has:
            return None
        if left_has and not right_has:
            return left
        if right_has and not left_has:
            return right
        lv = float(values.get(left))
        rv = float(values.get(right))
        if abs(lv - rv) <= 1e-9:
            return "tie"
        pref = str(row.get("preference") or "higher_is_better").strip().lower()
        if pref == "lower_is_better":
            return left if lv < rv else right
        return left if lv > rv else right

    left = ""
    right = ""
    pair_items = list(head_to_head_pair or [])
    if len(pair_items) >= 2:
        left = str(pair_items[0] or "").strip()
        right = str(pair_items[1] or "").strip()
    if not left or not right or left == right or left not in agent_ids or right not in agent_ids:
        left = ""
        right = ""

    h2h_counted = 0
    h2h_left_points = 0.0
    h2h_right_points = 0.0
    h2h_ties = 0
    h2h_ties_observed = 0
    h2h_decisive_counted = 0
    h2h_decisive_left_points = 0.0
    h2h_decisive_right_points = 0.0
    h2h_by_mode_counted: Counter[str] = Counter()
    h2h_by_mode_ties: Counter[str] = Counter()
    h2h_by_mode_ties_observed: Counter[str] = Counter()
    h2h_by_mode_left_points: Counter[str] = Counter()
    h2h_by_mode_right_points: Counter[str] = Counter()
    if left and right:
        for row in _iter_runtime_metric_rows(result):
            mode = _normalize_test_mode(row.get("test_mode"), category=row.get("category"))
            winner = _pairwise_metric_outcome(row, left, right)
            if winner is None:
                continue
            if winner == "tie":
                h2h_ties_observed += 1
                h2h_by_mode_ties_observed[mode] += 1
                if tie_policy == "exclude":
                    continue
                h2h_counted += 1
                h2h_by_mode_counted[mode] += 1
                h2h_ties += 1
                h2h_left_points += 0.5
                h2h_right_points += 0.5
                h2h_by_mode_ties[mode] += 1
                h2h_by_mode_left_points[mode] += 0.5
                h2h_by_mode_right_points[mode] += 0.5
            elif winner == left:
                h2h_decisive_counted += 1
                h2h_decisive_left_points += 1.0
                h2h_counted += 1
                h2h_by_mode_counted[mode] += 1
                h2h_left_points += 1.0
                h2h_by_mode_left_points[mode] += 1.0
            elif winner == right:
                h2h_decisive_counted += 1
                h2h_decisive_right_points += 1.0
                h2h_counted += 1
                h2h_by_mode_counted[mode] += 1
                h2h_right_points += 1.0
                h2h_by_mode_right_points[mode] += 1.0
    h2h_left_score = round((h2h_left_points / h2h_counted) * 100.0, 3) if h2h_counted > 0 else None
    h2h_right_score = round((h2h_right_points / h2h_counted) * 100.0, 3) if h2h_counted > 0 else None
    h2h_decisive_left_score = (
        round((h2h_decisive_left_points / h2h_decisive_counted) * 100.0, 3) if h2h_decisive_counted > 0 else None
    )
    h2h_decisive_right_score = (
        round((h2h_decisive_right_points / h2h_decisive_counted) * 100.0, 3) if h2h_decisive_counted > 0 else None
    )
    h2h_by_mode: dict[str, dict[str, Any]] = {}
    for mode in sorted(set(DEFAULT_TEST_MODES) | set(h2h_by_mode_counted.keys())):
        counted = int(h2h_by_mode_counted.get(mode) or 0)
        left_points = float(h2h_by_mode_left_points.get(mode) or 0.0)
        right_points = float(h2h_by_mode_right_points.get(mode) or 0.0)
        h2h_by_mode[mode] = {
            "counted_metrics": counted,
            "ties": int(h2h_by_mode_ties.get(mode) or 0),
            "ties_observed": int(h2h_by_mode_ties_observed.get(mode) or 0),
            "agent_a_score": (round((left_points / counted) * 100.0, 3) if counted > 0 else None),
            "agent_b_score": (round((right_points / counted) * 100.0, 3) if counted > 0 else None),
        }

    token_rows: list[dict[str, Any]] = [_build_token_efficiency_row(result, aid) for aid in agent_ids]
    token_map = {str(row.get("agent") or "").strip(): row for row in token_rows if str(row.get("agent") or "").strip()}
    token_ranking = sorted(
        list(token_rows),
        key=lambda row: (
            float(row.get("token_efficiency_score") or -1.0),
            float(row.get("telemetry_coverage") or 0.0),
            -float(row.get("effective_tokens_per_success") or float("inf")),
        ),
        reverse=True,
    )
    for idx, row in enumerate(token_ranking, start=1):
        row["token_efficiency_rank"] = int(idx)

    token_h2h_counted = 0
    token_h2h_ties = 0
    token_h2h_left_points = 0.0
    token_h2h_right_points = 0.0
    token_h2h_components: list[dict[str, Any]] = []
    if left and right:
        left_token = dict(token_map.get(left) or {})
        right_token = dict(token_map.get(right) or {})
        if bool(left_token.get("has_token_evidence")) or bool(right_token.get("has_token_evidence")):
            component_specs = [
                ("token_efficiency_score", "higher_is_better"),
                ("effective_tokens_per_success", "lower_is_better"),
                ("telemetry_coverage", "higher_is_better"),
            ]
            for metric, preference in component_specs:
                outcome = _pairwise_scalar_outcome(
                    left_token.get(metric), right_token.get(metric), preference=preference
                )
                if outcome is None:
                    continue
                token_h2h_counted += 1
                winner = ""
                if outcome == "tie":
                    token_h2h_ties += 1
                    token_h2h_left_points += 0.5
                    token_h2h_right_points += 0.5
                    winner = "tie"
                elif outcome == "left":
                    token_h2h_left_points += 1.0
                    winner = left
                elif outcome == "right":
                    token_h2h_right_points += 1.0
                    winner = right
                token_h2h_components.append(
                    {
                        "metric": metric,
                        "preference": preference,
                        "agent_a_value": left_token.get(metric),
                        "agent_b_value": right_token.get(metric),
                        "winner": winner,
                    }
                )
    token_h2h_left_score = (
        round((token_h2h_left_points / token_h2h_counted) * 100.0, 3) if token_h2h_counted > 0 else None
    )
    token_h2h_right_score = (
        round((token_h2h_right_points / token_h2h_counted) * 100.0, 3) if token_h2h_counted > 0 else None
    )

    agent_score_rows: list[dict[str, Any]] = []
    for aid in agent_ids:
        runtime_applicable = 0
        runtime_passed = 0
        runtime_applicable_by_mode: Counter[str] = Counter()
        runtime_passed_by_mode: Counter[str] = Counter()
        for row in _iter_runtime_metric_rows(result):
            mode = _normalize_test_mode(row.get("test_mode"), category=row.get("category"))
            values = dict(row.get("values") or {})
            if not _is_number(values.get(aid)):
                continue
            runtime_applicable += 1
            runtime_applicable_by_mode[mode] += 1
            winners = set(str(item).strip() for item in (row.get("winners") or []) if str(item).strip())
            if aid in winners:
                runtime_passed += 1
                runtime_passed_by_mode[mode] += 1

        catalog_rows_for_agent = _build_catalog_rows_for_agent(aid)
        catalog_applicable = 0
        catalog_passed_agent = 0
        catalog_applicable_by_mode: Counter[str] = Counter()
        catalog_passed_by_mode: Counter[str] = Counter()
        for row in catalog_rows_for_agent:
            mode = _normalize_test_mode(row.get("test_mode"), category=row.get("category"))
            if not bool(row.get("applicable")):
                continue
            catalog_applicable += 1
            catalog_applicable_by_mode[mode] += 1
            if bool(row.get("evaluated_pass")):
                catalog_passed_agent += 1
                catalog_passed_by_mode[mode] += 1
        overall_applicable = runtime_applicable + catalog_applicable
        overall_passed = runtime_passed + catalog_passed_agent
        overall_score = round((overall_passed / overall_applicable) * 100.0, 3) if overall_applicable > 0 else 0.0
        observed_modes = sorted(
            set(DEFAULT_TEST_MODES) | set(runtime_applicable_by_mode.keys()) | set(catalog_applicable_by_mode.keys())
        )
        mode_scores: dict[str, dict[str, Any]] = {}
        for mode in observed_modes:
            mode_runtime_applicable = int(runtime_applicable_by_mode.get(mode) or 0)
            mode_runtime_passed = int(runtime_passed_by_mode.get(mode) or 0)
            mode_catalog_applicable = int(catalog_applicable_by_mode.get(mode) or 0)
            mode_catalog_passed = int(catalog_passed_by_mode.get(mode) or 0)
            mode_overall_applicable = int(mode_runtime_applicable + mode_catalog_applicable)
            mode_overall_passed = int(mode_runtime_passed + mode_catalog_passed)
            mode_score = (
                round((mode_overall_passed / mode_overall_applicable) * 100.0, 3)
                if mode_overall_applicable > 0
                else 0.0
            )
            mode_scores[mode] = {
                "runtime_applicable": mode_runtime_applicable,
                "runtime_passed": mode_runtime_passed,
                "catalog_applicable": mode_catalog_applicable,
                "catalog_passed": mode_catalog_passed,
                "overall_applicable": mode_overall_applicable,
                "overall_passed": mode_overall_passed,
                "suite_score": mode_score,
            }
        if left and right and aid == left:
            head_to_head = h2h_left_score
            head_to_head_decisive = h2h_decisive_left_score
        elif left and right and aid == right:
            head_to_head = h2h_right_score
            head_to_head_decisive = h2h_decisive_right_score
        else:
            head_to_head = None
            head_to_head_decisive = None
        token_row = dict(token_map.get(aid) or {})
        agent_score_rows.append(
            {
                "agent": aid,
                "head_to_head_score": head_to_head,
                "head_to_head_decisive_score": head_to_head_decisive,
                "overall_suite_score": overall_score,
                "quick_suite_score": float(dict(mode_scores.get("quick") or {}).get("suite_score") or 0.0),
                "dynamic_suite_score": float(dict(mode_scores.get("dynamic") or {}).get("suite_score") or 0.0),
                "human_suite_score": float(dict(mode_scores.get("human") or {}).get("suite_score") or 0.0),
                "token_efficiency_score": (
                    round(float(token_row.get("token_efficiency_score")), 6)
                    if _is_number(token_row.get("token_efficiency_score"))
                    else None
                ),
                "token_efficiency_tokens_per_success": (
                    round(float(token_row.get("effective_tokens_per_success")), 6)
                    if _is_number(token_row.get("effective_tokens_per_success"))
                    else None
                ),
                "token_efficiency_telemetry_coverage": (
                    round(float(token_row.get("telemetry_coverage")), 6)
                    if _is_number(token_row.get("telemetry_coverage"))
                    else 0.0
                ),
                "runtime_checks": {
                    "applicable": int(runtime_applicable),
                    "passed": int(runtime_passed),
                    "pass_ratio": (round(runtime_passed / runtime_applicable, 6) if runtime_applicable > 0 else 0.0),
                },
                "catalog_checks": {
                    "applicable": int(catalog_applicable),
                    "passed": int(catalog_passed_agent),
                    "pass_ratio": (
                        round(catalog_passed_agent / catalog_applicable, 6) if catalog_applicable > 0 else 0.0
                    ),
                },
                "overall_checks": {
                    "applicable": int(overall_applicable),
                    "passed": int(overall_passed),
                    "pass_ratio": (round(overall_passed / overall_applicable, 6) if overall_applicable > 0 else 0.0),
                },
                "mode_scores": mode_scores,
            }
        )
    mode_rankings: dict[str, list[dict[str, Any]]] = {}
    all_modes = sorted(set(DEFAULT_TEST_MODES) | set(by_mode.keys()))
    for mode in all_modes:
        ranked_mode_rows = sorted(
            list(agent_score_rows),
            key=lambda row: (
                float(dict(dict(row.get("mode_scores") or {}).get(mode) or {}).get("suite_score") or 0.0),
                float(row.get("token_efficiency_score") or -1.0),
                float(row.get("head_to_head_score") or -1.0),
            ),
            reverse=True,
        )
        mode_rows: list[dict[str, Any]] = []
        for idx, row in enumerate(ranked_mode_rows, start=1):
            mode_data = dict(dict(row.get("mode_scores") or {}).get(mode) or {})
            row[f"{mode}_suite_rank"] = int(idx)
            mode_rows.append(
                {
                    "agent": str(row.get("agent") or ""),
                    "rank": int(idx),
                    "suite_score": float(mode_data.get("suite_score") or 0.0),
                    "overall_applicable": int(mode_data.get("overall_applicable") or 0),
                    "overall_passed": int(mode_data.get("overall_passed") or 0),
                }
            )
        mode_rankings[mode] = mode_rows

    overall_ranking = sorted(
        list(agent_score_rows),
        key=lambda row: (
            float(row.get("overall_suite_score") or 0.0),
            float(row.get("token_efficiency_score") or -1.0),
            float(row.get("head_to_head_score") or -1.0),
        ),
        reverse=True,
    )
    for idx, row in enumerate(overall_ranking, start=1):
        row["overall_rank"] = int(idx)

    return {
        "focus_agent": focus,
        "contract_id": str(contract.get("id") or ""),
        "contract_version": int(contract.get("version") or 1),
        "scoring_methodology": {
            "head_to_head_score": "explicit 1v1 pair; counts runtime metrics where either side has data; excludes metrics where neither side has data; tie handling follows suite head_to_head_tie_policy",
            "overall_suite_score": "all applicable runtime metric checks + all applicable catalog contract checks",
            "lane_suite_scores": "quick/dynamic/human suite scores use the same formula but only checks tagged to that mode",
            "token_efficiency_score": "token-aware blended score using effective tokens per success, token telemetry coverage, success quality, and cost probe reliability",
        },
        "runtime_metrics": {
            "total": runtime_total,
            "with_focus_data": int(runtime_metrics_with_focus_data),
            "comparable": int(runtime_metrics_comparable),
            "by_mode": {
                mode: {
                    "total": int(runtime_metrics_by_mode_total.get(mode) or 0),
                    "with_focus_data": int(runtime_metrics_by_mode_with_focus_data.get(mode) or 0),
                    "comparable": int(runtime_metrics_by_mode_comparable.get(mode) or 0),
                }
                for mode in sorted(set(DEFAULT_TEST_MODES) | set(runtime_metrics_by_mode_total.keys()))
            },
            "metric_ids": sorted(set(runtime_metric_ids)),
        },
        "catalog": {
            "total": catalog_total,
            "by_state": dict(by_state),
            "by_evaluation": dict(by_eval),
            "by_category": dict(by_category),
            "by_mode": dict(by_mode),
            "checks": catalog_rows,
        },
        "summary": {
            "tracked_total": int(tracked_total),
            "implemented_total": int(implemented_total),
            "planned_total": int(max(0, tracked_total - implemented_total)),
            "implemented_ratio": (round(implemented_total / tracked_total, 6) if tracked_total > 0 else 1.0),
            "catalog_passed_total": int(catalog_passed),
            "catalog_failed_total": int(catalog_failed),
            "catalog_pass_ratio": (round(catalog_passed / catalog_total, 6) if catalog_total > 0 else 1.0),
        },
        "scores": {
            "agents": agent_score_rows,
            "overall_ranking": overall_ranking,
            "mode_rankings": mode_rankings,
            "head_to_head": {
                "enabled": bool(left and right),
                "agent_a": left,
                "agent_b": right,
                "tie_policy": tie_policy,
                "counted_metrics": int(h2h_counted),
                "ties": int(h2h_ties),
                "ties_observed": int(h2h_ties_observed),
                "agent_a_score": h2h_left_score,
                "agent_b_score": h2h_right_score,
                "decisive_counted_metrics": int(h2h_decisive_counted),
                "decisive_agent_a_score": h2h_decisive_left_score,
                "decisive_agent_b_score": h2h_decisive_right_score,
                "by_mode": h2h_by_mode,
            },
            "token_efficiency": {
                "methodology": "1v1 uses token_efficiency_score, effective_tokens_per_success, and telemetry_coverage; overall ranks by token_efficiency_score",
                "agents": token_rows,
                "overall_ranking": token_ranking,
                "head_to_head": {
                    "enabled": bool(left and right),
                    "agent_a": left,
                    "agent_b": right,
                    "counted_metrics": int(token_h2h_counted),
                    "ties": int(token_h2h_ties),
                    "agent_a_score": token_h2h_left_score,
                    "agent_b_score": token_h2h_right_score,
                    "components": token_h2h_components,
                },
            },
        },
        "errors": [str(item) for item in (contract.get("errors") or []) if str(item).strip()],
    }


def render_test_suite_contract_markdown(evaluation: Mapping[str, Any]) -> str:
    runtime = dict(evaluation.get("runtime_metrics") or {})
    catalog = dict(evaluation.get("catalog") or {})
    summary = dict(evaluation.get("summary") or {})
    head_to_head = dict(dict(evaluation.get("scores") or {}).get("head_to_head") or {})
    mode_rankings = dict(dict(evaluation.get("scores") or {}).get("mode_rankings") or {})
    token_efficiency = dict(dict(evaluation.get("scores") or {}).get("token_efficiency") or {})
    token_h2h = dict(token_efficiency.get("head_to_head") or {})
    token_ranking = list(token_efficiency.get("overall_ranking") or [])
    lines: list[str] = []
    lines.append("# Full Coverage Test Suite Contract")
    lines.append("")
    lines.append(f"- Focus agent: `{evaluation.get('focus_agent')}`")
    lines.append(f"- Contract: `{evaluation.get('contract_id')}` v`{evaluation.get('contract_version')}`")
    lines.append(
        f"- Tracked checks: `{summary.get('tracked_total')}`, implemented: `{summary.get('implemented_total')}`, "
        f"planned: `{summary.get('planned_total')}`, implemented ratio: `{summary.get('implemented_ratio')}`"
    )
    lines.append("")
    lines.append("## Runtime Metrics")
    lines.append("")
    lines.append(
        f"- Total runtime metric checks: `{runtime.get('total')}` "
        f"(focus data: `{runtime.get('with_focus_data')}`, comparable: `{runtime.get('comparable')}`)"
    )
    runtime_by_mode = dict(runtime.get("by_mode") or {})
    if runtime_by_mode:
        for mode in sorted(runtime_by_mode.keys()):
            row = dict(runtime_by_mode.get(mode) or {})
            lines.append(
                f"- `{mode}` runtime checks: total `{row.get('total', 0)}`, "
                f"focus-data `{row.get('with_focus_data', 0)}`, comparable `{row.get('comparable', 0)}`"
            )
    lines.append("")
    lines.append("## Catalog Check State")
    lines.append("")
    by_state = dict(catalog.get("by_state") or {})
    if not by_state:
        lines.append("- none")
    else:
        for state in sorted(by_state.keys()):
            lines.append(f"- `{state}`: `{by_state[state]}`")
    by_eval = dict(catalog.get("by_evaluation") or {})
    if by_eval:
        lines.append(f"- `evaluation.pass`: `{by_eval.get('pass', 0)}`")
        lines.append(f"- `evaluation.fail`: `{by_eval.get('fail', 0)}`")
    lines.append("")
    lines.append("## Catalog By Category")
    lines.append("")
    by_category = dict(catalog.get("by_category") or {})
    if not by_category:
        lines.append("- none")
    else:
        for category in sorted(by_category.keys()):
            lines.append(f"- `{category}`: `{by_category[category]}`")
    lines.append("")
    lines.append("## Lane Scores")
    lines.append("")
    if not mode_rankings:
        lines.append("- none")
    else:
        for mode in sorted(mode_rankings.keys()):
            rows = list(mode_rankings.get(mode) or [])
            if not rows:
                continue
            top = rows[0]
            lines.append(
                f"- `{mode}` leader: `{top.get('agent')}` score `{top.get('suite_score')}` "
                f"(passed `{top.get('overall_passed')}` / applicable `{top.get('overall_applicable')}`)"
            )
    lines.append("")
    lines.append("## Head-to-Head")
    lines.append("")
    if bool(head_to_head.get("enabled")):
        lines.append(
            f"- tie_policy `{head_to_head.get('tie_policy')}`, counted `{head_to_head.get('counted_metrics')}`, "
            f"ties_counted `{head_to_head.get('ties')}`, ties_observed `{head_to_head.get('ties_observed')}`"
        )
        lines.append(
            f"- decisive (ties excluded): `{head_to_head.get('agent_a')}`=`{head_to_head.get('decisive_agent_a_score')}`, "
            f"`{head_to_head.get('agent_b')}`=`{head_to_head.get('decisive_agent_b_score')}` "
            f"(counted `{head_to_head.get('decisive_counted_metrics')}`)"
        )
    else:
        lines.append("- not configured")
    lines.append("")
    lines.append("## Token Efficiency")
    lines.append("")
    lines.append(f"- Method: `{token_efficiency.get('methodology')}`")
    if bool(token_h2h.get("enabled")):
        lines.append(
            f"- 1v1: `{token_h2h.get('agent_a')}`=`{token_h2h.get('agent_a_score')}`, "
            f"`{token_h2h.get('agent_b')}`=`{token_h2h.get('agent_b_score')}` "
            f"(counted `{token_h2h.get('counted_metrics')}`, ties `{token_h2h.get('ties')}`)"
        )
    else:
        lines.append("- 1v1: not configured")
    if token_ranking:
        for row in token_ranking[:5]:
            lines.append(
                f"- `#{row.get('token_efficiency_rank')}` `{row.get('agent')}`: "
                f"score `{row.get('token_efficiency_score')}`, "
                f"tokens_per_success `{row.get('effective_tokens_per_success')}`, "
                f"coverage `{row.get('telemetry_coverage')}`"
            )
    lines.append("")
    return "\n".join(lines)
