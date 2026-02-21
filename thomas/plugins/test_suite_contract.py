from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence


def load_test_suite_contract(path: Path) -> Dict[str, Any]:
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


def _agent_metrics(result: Mapping[str, Any], agent_id: str) -> Dict[str, Any]:
    aid = str(agent_id or "").strip()
    for row in list(result.get("agents") or []):
        if not isinstance(row, dict):
            continue
        if str(row.get("id") or "").strip() != aid:
            continue
        return dict(row.get("metrics") or {})
    return {}


def _check_signals(result: Mapping[str, Any], agent_id: str) -> Dict[str, bool]:
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


def evaluate_test_suite_contract(
    *,
    contract: Mapping[str, Any],
    result: Mapping[str, Any],
    focus_agent: str,
    head_to_head_pair: Sequence[str] | None = None,
) -> Dict[str, Any]:
    focus = str(focus_agent or "").strip()
    runtime_metric_ids: List[str] = []
    runtime_metrics_with_focus_data = 0
    runtime_metrics_comparable = 0
    for row in _iter_runtime_metric_rows(result):
        metric = str(row.get("metric") or "").strip()
        if not metric:
            continue
        runtime_metric_ids.append(metric)
        values = dict(row.get("values") or {})
        if _is_number(values.get(focus)):
            runtime_metrics_with_focus_data += 1
        participants = list(row.get("participants") or [])
        if len(participants) >= 2:
            runtime_metrics_comparable += 1

    catalog_checks_raw = [row for row in list(contract.get("catalog_checks") or []) if isinstance(row, dict)]

    def _build_catalog_rows_for_agent(agent_id: str) -> List[Dict[str, Any]]:
        category_signals = _check_signals(result, agent_id)
        rows: List[Dict[str, Any]] = []
        for raw in catalog_checks_raw:
            rid = str(raw.get("id") or "").strip()
            if not rid:
                continue
            state = str(raw.get("implementation_state") or "planned").strip().lower()
            category = str(raw.get("category") or "uncategorized").strip()
            title = str(raw.get("title") or rid).strip()
            applicable = category in category_signals
            passed = bool(category_signals.get(category, False)) if applicable else False
            rows.append(
                {
                    "id": rid,
                    "category": category,
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
    if left and right:
        for row in _iter_runtime_metric_rows(result):
            winner = _pairwise_metric_outcome(row, left, right)
            if winner is None:
                continue
            h2h_counted += 1
            if winner == "tie":
                h2h_ties += 1
                h2h_left_points += 0.5
                h2h_right_points += 0.5
            elif winner == left:
                h2h_left_points += 1.0
            elif winner == right:
                h2h_right_points += 1.0
    h2h_left_score = (round((h2h_left_points / h2h_counted) * 100.0, 3) if h2h_counted > 0 else None)
    h2h_right_score = (round((h2h_right_points / h2h_counted) * 100.0, 3) if h2h_counted > 0 else None)

    agent_score_rows: List[Dict[str, Any]] = []
    for aid in agent_ids:
        runtime_applicable = 0
        runtime_passed = 0
        for row in _iter_runtime_metric_rows(result):
            values = dict(row.get("values") or {})
            if not _is_number(values.get(aid)):
                continue
            runtime_applicable += 1
            winners = set(str(item).strip() for item in (row.get("winners") or []) if str(item).strip())
            if aid in winners:
                runtime_passed += 1

        catalog_rows_for_agent = _build_catalog_rows_for_agent(aid)
        catalog_applicable = sum(1 for row in catalog_rows_for_agent if bool(row.get("applicable")))
        catalog_passed_agent = sum(
            1 for row in catalog_rows_for_agent if bool(row.get("applicable")) and bool(row.get("evaluated_pass"))
        )
        overall_applicable = runtime_applicable + catalog_applicable
        overall_passed = runtime_passed + catalog_passed_agent
        overall_score = (round((overall_passed / overall_applicable) * 100.0, 3) if overall_applicable > 0 else 0.0)
        if left and right and aid == left:
            head_to_head = h2h_left_score
        elif left and right and aid == right:
            head_to_head = h2h_right_score
        else:
            head_to_head = None
        agent_score_rows.append(
            {
                "agent": aid,
                "head_to_head_score": head_to_head,
                "overall_suite_score": overall_score,
                "runtime_checks": {
                    "applicable": int(runtime_applicable),
                    "passed": int(runtime_passed),
                    "pass_ratio": (round(runtime_passed / runtime_applicable, 6) if runtime_applicable > 0 else 0.0),
                },
                "catalog_checks": {
                    "applicable": int(catalog_applicable),
                    "passed": int(catalog_passed_agent),
                    "pass_ratio": (round(catalog_passed_agent / catalog_applicable, 6) if catalog_applicable > 0 else 0.0),
                },
                "overall_checks": {
                    "applicable": int(overall_applicable),
                    "passed": int(overall_passed),
                    "pass_ratio": (round(overall_passed / overall_applicable, 6) if overall_applicable > 0 else 0.0),
                },
            }
        )
    overall_ranking = sorted(
        list(agent_score_rows),
        key=lambda row: (
            float(row.get("overall_suite_score") or 0.0),
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
            "head_to_head_score": "explicit 1v1 pair; counts runtime metrics where either side has data; excludes metrics where neither side has data",
            "overall_suite_score": "all applicable runtime metric checks + all applicable catalog contract checks",
        },
        "runtime_metrics": {
            "total": runtime_total,
            "with_focus_data": int(runtime_metrics_with_focus_data),
            "comparable": int(runtime_metrics_comparable),
            "metric_ids": sorted(set(runtime_metric_ids)),
        },
        "catalog": {
            "total": catalog_total,
            "by_state": dict(by_state),
            "by_evaluation": dict(by_eval),
            "by_category": dict(by_category),
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
            "head_to_head": {
                "enabled": bool(left and right),
                "agent_a": left,
                "agent_b": right,
                "counted_metrics": int(h2h_counted),
                "ties": int(h2h_ties),
                "agent_a_score": h2h_left_score,
                "agent_b_score": h2h_right_score,
            },
        },
        "errors": [str(item) for item in (contract.get("errors") or []) if str(item).strip()],
    }


def render_test_suite_contract_markdown(evaluation: Mapping[str, Any]) -> str:
    runtime = dict(evaluation.get("runtime_metrics") or {})
    catalog = dict(evaluation.get("catalog") or {})
    summary = dict(evaluation.get("summary") or {})
    lines: List[str] = []
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
    return "\n".join(lines)
