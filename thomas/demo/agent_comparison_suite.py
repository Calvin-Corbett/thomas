from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from thomas.demo.agent_comparison_suite_metrics import (
    _build_metric_specs,
    _collect_agent_metrics,
)
from thomas.demo.agent_comparison_suite_scoring import (
    _build_competitor_pressure,
    _build_metric_rows,
    _build_scoreboard,
    _focus_gaps,
)
from thomas.demo.agent_comparison_suite_shared import (
    MetricSpec,
    _assertion_ok,
    _collect_git_version_info,
    _collect_model_snapshot,
    _resolve_path_value,
    DEFAULT_CATEGORY_WEIGHTS,
    DEFAULT_EXECUTION_POLICY,
    DEFAULT_GATEWAY_PATTERNS,
    DEFAULT_REGISTRY_MD_PATH,
    DEFAULT_REGISTRY_PATH,
    DEFAULT_SUITE_CONFIG,
    DEFAULT_TEST_SUITE_CONTRACT_PATH,
    DEFAULT_WRITE_MD_PATH,
    DEFAULT_WRITE_PATH,
    ROOT,
    _is_number,
    _materialize_competitor_catalog_agents,
    _now_iso,
    _read_json,
    _update_competitor_registry,
    _write_json,
)
from thomas.demo.agent_comparison_suite_strict_checks import (
    _collect_benchmark_evidence,
    _collect_benchmark_summary,
    _compute_token_efficiency,
    _count_regex_hits,
    _run_probe_suite,
)
from thomas.plugins.benchmark_program import evaluate_benchmark_program
from thomas.plugins.competitor_evo_scope import build_prediction_evo_scope
from thomas.plugins.competitor_intel_store import load_registry
from thomas.plugins.test_suite_contract import evaluate_test_suite_contract, load_test_suite_contract


def load_suite_config(path: Path) -> dict[str, Any]:
    data = _read_json(path)
    agents = data.get("agents")
    if not isinstance(agents, list) or not agents:
        raise ValueError("suite config requires non-empty 'agents' list")
    normalized_agents: list[dict[str, Any]] = []
    for idx, raw in enumerate(agents, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"agents[{idx}] must be an object")
        aid = str(raw.get("id") or "").strip()
        if not aid:
            raise ValueError(f"agents[{idx}] is missing id")
        root = str(raw.get("root") or ".").strip()
        normalized = dict(raw)
        normalized["id"] = aid
        normalized["root"] = root
        normalized_agents.append(normalized)

    tracked_cli = [str(item).strip() for item in (data.get("tracked_cli_commands") or []) if str(item).strip()]
    if not tracked_cli:
        infer: list[str] = []
        for agent in normalized_agents:
            fixed_depth = dict((dict(agent.get("cli") or {})).get("fixed_subcommand_depth") or {})
            for name in fixed_depth:
                text = str(name).strip()
                if text and text not in infer:
                    infer.append(text)
        tracked_cli = sorted(infer)

    category_weights = dict(DEFAULT_CATEGORY_WEIGHTS)
    category_weights.update(dict(data.get("category_weights") or {}))
    metric_weight_overrides = dict(data.get("metric_weight_overrides") or {})
    competitor_catalog = [item for item in (data.get("competitor_catalog") or []) if isinstance(item, dict)]
    test_suite_contract_path = str(
        data.get("test_suite_contract_path") or str(DEFAULT_TEST_SUITE_CONTRACT_PATH)
    ).strip()
    execution_policy = dict(DEFAULT_EXECUTION_POLICY)
    execution_policy.update(dict(data.get("execution_policy") or {}))
    head_to_head_pair = [str(item).strip() for item in (data.get("head_to_head_pair") or []) if str(item).strip()]
    if len(head_to_head_pair) != 2:
        head_to_head_pair = []
    tie_policy = str(data.get("head_to_head_tie_policy") or "half_point").strip().lower()
    if tie_policy not in {"half_point", "exclude"}:
        tie_policy = "half_point"

    return {
        "id": str(data.get("id") or path.stem),
        "version": int(data.get("version") or 1),
        "description": str(data.get("description") or "").strip(),
        "tracked_cli_commands": tracked_cli,
        "category_weights": category_weights,
        "metric_weight_overrides": metric_weight_overrides,
        "competitor_catalog": competitor_catalog,
        "test_suite_contract_path": test_suite_contract_path,
        "execution_policy": execution_policy,
        "head_to_head_pair": head_to_head_pair,
        "head_to_head_tie_policy": tie_policy,
        "agents": normalized_agents,
    }


def build_suite_result(
    *,
    suite_config: Mapping[str, Any],
    suite_path: Path,
    focus_agent: str,
    top_gaps: int,
    head_to_head_pair: Sequence[str] | None = None,
    previous_registry_competitors: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    tracked_cli = list(suite_config.get("tracked_cli_commands") or [])
    category_weights = dict(suite_config.get("category_weights") or {})
    metric_weight_overrides = dict(suite_config.get("metric_weight_overrides") or {})
    execution_policy = dict(DEFAULT_EXECUTION_POLICY)
    execution_policy.update(dict(suite_config.get("execution_policy") or {}))
    suite_root = suite_path.parent.parent.parent.resolve()
    contract_path = Path(str(suite_config.get("test_suite_contract_path") or str(DEFAULT_TEST_SUITE_CONTRACT_PATH)))
    if not contract_path.is_absolute():
        contract_path = (suite_root / contract_path).resolve()
    contract = load_test_suite_contract(contract_path)
    prepared_agents, preparation = _materialize_competitor_catalog_agents(
        suite_config=suite_config,
        suite_root=suite_root,
    )

    agent_payloads: list[dict[str, Any]] = []
    gateway_keys: set[str] = set()
    for agent in prepared_agents:
        agent_payload = _collect_agent_metrics(
            agent,
            tracked_commands=tracked_cli,
            suite_root=suite_root,
        )
        agent_payloads.append(agent_payload)
        patterns = dict(DEFAULT_GATEWAY_PATTERNS)
        patterns.update(dict(agent.get("gateway_patterns") or {}))
        gateway_keys.update(patterns.keys())

    metric_specs = _build_metric_specs(
        tracked_cli_commands=tracked_cli,
        gateway_pattern_keys=sorted(gateway_keys),
        category_weights=category_weights,
        weight_overrides=metric_weight_overrides,
    )
    metric_rows = _build_metric_rows(metric_specs=metric_specs, agents=agent_payloads)
    scoreboard = _build_scoreboard(metric_rows, agents=agent_payloads)
    focus_gap_rows = _focus_gaps(metric_rows, focus_agent=focus_agent, top_n=top_gaps)
    competitor_pressure = _build_competitor_pressure(
        rows=metric_rows,
        scoreboard=scoreboard,
        focus_agent=focus_agent,
    )
    prediction_evo_scope = build_prediction_evo_scope(
        agents=agent_payloads,
        previous_registry_competitors=(previous_registry_competitors or {}),
        focus_agent=focus_agent,
    )

    result: dict[str, Any] = {
        "computed_at_utc": _now_iso(),
        "suite": {
            "id": str(suite_config.get("id") or ""),
            "version": int(suite_config.get("version") or 1),
            "description": str(suite_config.get("description") or ""),
            "config_path": str(suite_path),
            "test_suite_contract_path": str(contract_path),
            "execution_policy": execution_policy,
            "head_to_head_pair": list(head_to_head_pair or []),
            "head_to_head_tie_policy": str(suite_config.get("head_to_head_tie_policy") or "half_point"),
            "tracked_cli_commands": tracked_cli,
            "category_weights": category_weights,
            "metric_weight_overrides": metric_weight_overrides,
            "competitor_catalog_count": len(list(suite_config.get("competitor_catalog") or [])),
        },
        "preparation": preparation,
        "agents": agent_payloads,
        "metric_board": metric_rows,
        "scoreboard": scoreboard,
        "prediction_evo_scope": prediction_evo_scope,
        "focus": {
            "agent": str(focus_agent),
            "open_gaps": focus_gap_rows,
            "open_gap_count": len(focus_gap_rows),
            "competitor_pressure": competitor_pressure,
            "competitors_beating_focus": list(competitor_pressure.get("top_threats") or []),
        },
    }
    result["test_suite_contract"] = evaluate_test_suite_contract(
        contract=contract,
        result=result,
        focus_agent=focus_agent,
        head_to_head_pair=head_to_head_pair,
    )
    result["benchmark_program"] = evaluate_benchmark_program(
        contract=contract,
        result=result,
        contract_evaluation=dict(result.get("test_suite_contract") or {}),
    )
    contract_scores = list((dict(result.get("test_suite_contract") or {}).get("scores") or {}).get("agents") or [])
    score_map = {
        str(row.get("agent") or "").strip(): dict(row) for row in contract_scores if str(row.get("agent") or "").strip()
    }
    benchmark_rows = list(dict(result.get("benchmark_program") or {}).get("ranking") or [])
    benchmark_map = {
        str(row.get("agent") or "").strip(): dict(row) for row in benchmark_rows if str(row.get("agent") or "").strip()
    }
    ranking_rows = list((dict(result.get("scoreboard") or {})).get("ranking") or [])
    for row in ranking_rows:
        aid = str(row.get("agent") or "").strip()
        ext = dict(score_map.get(aid) or {})
        row["head_to_head_score"] = (
            round(float(ext.get("head_to_head_score")), 3) if _is_number(ext.get("head_to_head_score")) else None
        )
        row["head_to_head_decisive_score"] = (
            round(float(ext.get("head_to_head_decisive_score")), 3)
            if _is_number(ext.get("head_to_head_decisive_score"))
            else None
        )
        row["token_efficiency_score"] = (
            round(float(ext.get("token_efficiency_score")), 6)
            if _is_number(ext.get("token_efficiency_score"))
            else None
        )
        row["token_efficiency_tokens_per_success"] = (
            round(float(ext.get("token_efficiency_tokens_per_success")), 6)
            if _is_number(ext.get("token_efficiency_tokens_per_success"))
            else None
        )
        row["token_efficiency_telemetry_coverage"] = (
            round(float(ext.get("token_efficiency_telemetry_coverage")), 6)
            if _is_number(ext.get("token_efficiency_telemetry_coverage"))
            else 0.0
        )
        row["overall_suite_score"] = round(float(ext.get("overall_suite_score") or 0.0), 3)
        row["overall_suite_rank"] = int(ext.get("overall_rank") or 0)
        row["quick_suite_score"] = round(float(ext.get("quick_suite_score") or 0.0), 3)
        row["dynamic_suite_score"] = round(float(ext.get("dynamic_suite_score") or 0.0), 3)
        row["human_suite_score"] = round(float(ext.get("human_suite_score") or 0.0), 3)
        row["quick_suite_rank"] = int(ext.get("quick_suite_rank") or 0)
        row["dynamic_suite_rank"] = int(ext.get("dynamic_suite_rank") or 0)
        row["human_suite_rank"] = int(ext.get("human_suite_rank") or 0)
        bench = dict(benchmark_map.get(aid) or {})
        row["overall_benchmark_capability_score"] = round(
            float(bench.get("overall_benchmark_capability_score") or 0.0), 3
        )
        row["benchmark_program_rank"] = int(bench.get("rank") or 0)
        row["governance_verdict"] = str(bench.get("governance_verdict") or "NO_GO")
        lane_scores = dict(bench.get("lane_scores") or {})
        row["quick_lane_score"] = round(float(dict(lane_scores.get("quick") or {}).get("score") or 0.0), 3)
        row["dynamic_lane_score"] = round(float(dict(lane_scores.get("dynamic") or {}).get("score") or 0.0), 3)
    result["overall_suite_scoreboard"] = {
        "methodology": dict(dict(result.get("test_suite_contract") or {}).get("scoring_methodology") or {}),
        "ranking": sorted(
            [
                {
                    "agent": str(row.get("agent") or ""),
                    "head_to_head_score": (
                        round(float(row.get("head_to_head_score")), 3)
                        if _is_number(row.get("head_to_head_score"))
                        else None
                    ),
                    "head_to_head_decisive_score": (
                        round(float(row.get("head_to_head_decisive_score")), 3)
                        if _is_number(row.get("head_to_head_decisive_score"))
                        else None
                    ),
                    "token_efficiency_score": (
                        round(float(row.get("token_efficiency_score")), 6)
                        if _is_number(row.get("token_efficiency_score"))
                        else None
                    ),
                    "token_efficiency_tokens_per_success": (
                        round(float(row.get("token_efficiency_tokens_per_success")), 6)
                        if _is_number(row.get("token_efficiency_tokens_per_success"))
                        else None
                    ),
                    "token_efficiency_telemetry_coverage": round(
                        float(row.get("token_efficiency_telemetry_coverage") or 0.0), 6
                    ),
                    "overall_suite_score": round(float(row.get("overall_suite_score") or 0.0), 3),
                    "head_to_head_rank": int(row.get("rank") or 0),
                    "overall_suite_rank": int(row.get("overall_suite_rank") or 0),
                    "quick_suite_score": round(float(row.get("quick_suite_score") or 0.0), 3),
                    "dynamic_suite_score": round(float(row.get("dynamic_suite_score") or 0.0), 3),
                    "human_suite_score": round(float(row.get("human_suite_score") or 0.0), 3),
                    "quick_suite_rank": int(row.get("quick_suite_rank") or 0),
                    "dynamic_suite_rank": int(row.get("dynamic_suite_rank") or 0),
                    "human_suite_rank": int(row.get("human_suite_rank") or 0),
                    "overall_benchmark_capability_score": round(
                        float(row.get("overall_benchmark_capability_score") or 0.0), 3
                    ),
                    "benchmark_program_rank": int(row.get("benchmark_program_rank") or 0),
                    "governance_verdict": str(row.get("governance_verdict") or "NO_GO"),
                    "quick_lane_score": round(float(row.get("quick_lane_score") or 0.0), 3),
                    "dynamic_lane_score": round(float(row.get("dynamic_lane_score") or 0.0), 3),
                }
                for row in ranking_rows
            ],
            key=lambda item: int(item.get("overall_suite_rank") or 0)
            if int(item.get("overall_suite_rank") or 0) > 0
            else 9999,
        ),
    }
    return result


def _print_human(result: Mapping[str, Any]) -> None:
    suite = dict(result.get("suite") or {})
    scoreboard = dict(result.get("scoreboard") or {})
    runtime_ranking = list(scoreboard.get("ranking") or [])
    focus = dict(result.get("focus") or {})
    focus_gaps = list(focus.get("open_gaps") or [])
    pressure = dict(focus.get("competitor_pressure") or {})
    top_threats = list(pressure.get("top_threats") or [])
    prediction = dict(result.get("prediction_evo_scope") or {})
    contract = dict(result.get("test_suite_contract") or {})
    contract_summary = dict(contract.get("summary") or {})
    contract_runtime = dict(contract.get("runtime_metrics") or {})
    contract_catalog = dict((dict(contract.get("catalog") or {})).get("by_state") or {})
    dual_scoring = dict(result.get("overall_suite_scoreboard") or {})
    scoring_methodology = dict(dual_scoring.get("methodology") or {})
    ranking = list(dual_scoring.get("ranking") or [])
    runtime_map = {
        str(row.get("agent") or "").strip(): dict(row) for row in runtime_ranking if str(row.get("agent") or "").strip()
    }
    benchmark_program = dict(result.get("benchmark_program") or {})
    benchmark_ranking = list(benchmark_program.get("ranking") or [])
    h2h = dict(dict(contract.get("scores") or {}).get("head_to_head") or {})
    token_efficiency = dict(dict(contract.get("scores") or {}).get("token_efficiency") or {})
    token_h2h = dict(token_efficiency.get("head_to_head") or {})
    token_ranking = list(token_efficiency.get("overall_ranking") or [])

    print("Full Agent Comparison Suite")
    print(f"- suite: {suite.get('id')} v{suite.get('version')}")
    print(f"- computed at: {result.get('computed_at_utc')}")
    print(f"- config: {suite.get('config_path')}")
    policy = dict(suite.get("execution_policy") or {})
    if policy:
        print(
            f"- execution policy: quality_is_king={bool(policy.get('quality_is_king'))}, "
            f"cycle_limit_disabled={bool(policy.get('cycle_limit_disabled'))}"
        )
        if str(policy.get("stop_condition") or "").strip():
            print(f"- stop condition: {policy.get('stop_condition')}")
    print("")
    print("Ranking")
    if scoring_methodology:
        tie_policy = str(h2h.get("tie_policy") or "half_point")
        print(f"- head_to_head: {scoring_methodology.get('head_to_head_score')}")
        print(f"- token_efficiency: {scoring_methodology.get('token_efficiency_score')}")
        print(f"- overall_suite: {scoring_methodology.get('overall_suite_score')}")
        print(f"- lane_scores: {scoring_methodology.get('lane_suite_scores')}")
        print("- score math:")
        if tie_policy == "exclude":
            print("  - runtime head_to_head: winner=1, ties excluded, score=(points/counted_metrics)*100")
        else:
            print("  - runtime head_to_head: winner=1, tie=0.5, score=(points/counted_metrics)*100")
        print("  - head_to_head_decisive: winner=1, ties always excluded, score=(wins/non_tied_counted)*100")
        print("  - overall_suite: (runtime_passed + catalog_passed) / (runtime_applicable + catalog_applicable) * 100")
        print("  - lane_suite_scores: same formula as overall but mode-filtered by quick/dynamic/human tags")
        print("  - token_efficiency: separate token-only scoring block, emitted only with token telemetry evidence")
    for row in ranking:
        aid = str(row.get("agent") or "")
        runtime_row = dict(runtime_map.get(aid) or {})
        h2h_value = row.get("head_to_head_score")
        h2h_text = f"{h2h_value}" if _is_number(h2h_value) else "n/a"
        h2h_decisive_value = row.get("head_to_head_decisive_score")
        h2h_decisive_text = f"{h2h_decisive_value}" if _is_number(h2h_decisive_value) else "n/a"
        token_value = row.get("token_efficiency_score")
        token_text = f"{token_value}" if _is_number(token_value) else "n/a"
        print(
            f"- #{row.get('overall_suite_rank')} {row.get('agent')}: "
            f"overall_suite={row.get('overall_suite_score')} capability={row.get('overall_benchmark_capability_score')} "
            f"(quick={row.get('quick_suite_score')}, dynamic={row.get('dynamic_suite_score')}, human={row.get('human_suite_score')}), "
            f"(runtime_rank={runtime_row.get('rank')}, head_to_head={h2h_text}, decisive_h2h={h2h_decisive_text}, token_efficiency={token_text}), "
            f"verdict={row.get('governance_verdict')} "
            f"runtime_wins={runtime_row.get('wins')}, runtime_coverage={float(runtime_row.get('coverage') or 0.0) * 100:.1f}%"
        )
    print("")
    print("Head-to-Head (1v1)")
    if bool(h2h.get("enabled")):
        tie_policy = str(h2h.get("tie_policy") or "half_point")
        print(f"- pair: {h2h.get('agent_a')} vs {h2h.get('agent_b')}")
        print(
            f"- scores: {h2h.get('agent_a')}={h2h.get('agent_a_score')} "
            f"{h2h.get('agent_b')}={h2h.get('agent_b_score')} "
            f"(tie_policy={tie_policy}, counted_metrics={h2h.get('counted_metrics')}, "
            f"ties_counted={h2h.get('ties')}, ties_observed={h2h.get('ties_observed')})"
        )
        print(
            f"- decisive: {h2h.get('agent_a')}={h2h.get('decisive_agent_a_score')} "
            f"{h2h.get('agent_b')}={h2h.get('decisive_agent_b_score')} "
            f"(counted_metrics={h2h.get('decisive_counted_metrics')}, ties_excluded=True)"
        )
        h2h_by_mode = dict(h2h.get("by_mode") or {})
        for mode in ("quick", "dynamic", "human"):
            mode_row = dict(h2h_by_mode.get(mode) or {})
            counted = int(mode_row.get("counted_metrics") or 0)
            if counted <= 0:
                continue
            print(
                f"- by_mode.{mode}: {h2h.get('agent_a')}={mode_row.get('agent_a_score')} "
                f"{h2h.get('agent_b')}={mode_row.get('agent_b_score')} "
                f"(counted_metrics={counted}, ties_counted={mode_row.get('ties')}, "
                f"ties_observed={mode_row.get('ties_observed')})"
            )
    else:
        print("- not configured (use --h2h-a and --h2h-b for explicit 1v1).")
    print("")
    print("Token Efficiency")
    print(f"- method: {token_efficiency.get('methodology')}")
    if bool(token_h2h.get("enabled")):
        print(f"- pair: {token_h2h.get('agent_a')} vs {token_h2h.get('agent_b')}")
        print(
            f"- scores: {token_h2h.get('agent_a')}={token_h2h.get('agent_a_score')} "
            f"{token_h2h.get('agent_b')}={token_h2h.get('agent_b_score')} "
            f"(counted_metrics={token_h2h.get('counted_metrics')}, ties={token_h2h.get('ties')})"
        )
    else:
        print("- pair: not configured")
    for row in token_ranking[:6]:
        print(
            f"- #{row.get('token_efficiency_rank')} {row.get('agent')}: "
            f"score={row.get('token_efficiency_score')} "
            f"tokens_per_success={row.get('effective_tokens_per_success')} "
            f"coverage={row.get('telemetry_coverage')}"
        )
    print("")
    print("Benchmark Program")
    if benchmark_program:
        print(f"- id: {benchmark_program.get('id')}")
        lane_weights = dict(benchmark_program.get("lane_weights") or {})
        if lane_weights:
            joined = ", ".join(f"{k}={lane_weights[k]}" for k in sorted(lane_weights.keys()))
            print(f"- lane_weights: {joined}")
        verdict_counts = dict(benchmark_program.get("verdict_counts") or {})
        if verdict_counts:
            joined = ", ".join(f"{k}={verdict_counts[k]}" for k in sorted(verdict_counts.keys()))
            print(f"- verdict_counts: {joined}")
        for row in benchmark_ranking[:8]:
            print(
                f"- #{row.get('rank')} {row.get('agent')}: "
                f"capability={row.get('overall_benchmark_capability_score')} "
                f"quick={dict(row.get('lane_scores') or {}).get('quick', {}).get('score', 0.0)} "
                f"dynamic={dict(row.get('lane_scores') or {}).get('dynamic', {}).get('score', 0.0)} "
                f"verdict={row.get('governance_verdict')}"
            )
    print("")
    print("Metric Coverage")
    print(
        f"- total metrics: {scoreboard.get('total_metrics')} "
        f"(multi-agent measured: {scoreboard.get('measured_metrics')}, ties: {scoreboard.get('tie_metrics')})"
    )
    if contract:
        print("")
        print("Full Coverage Contract")
        print(
            f"- tracked checks: {contract_summary.get('tracked_total')} "
            f"(implemented={contract_summary.get('implemented_total')}, planned={contract_summary.get('planned_total')})"
        )
        print(
            f"- runtime metrics tracked: {contract_runtime.get('total')} "
            f"(focus data={contract_runtime.get('with_focus_data')}, comparable={contract_runtime.get('comparable')})"
        )
        if contract_catalog:
            states = ", ".join(f"{k}={contract_catalog[k]}" for k in sorted(contract_catalog.keys()))
            print(f"- catalog states: {states}")

    focus_agent = str(focus.get("agent") or "")
    if focus_agent:
        print("")
        print(f"Open Gaps For {focus_agent}")
        if not focus_gaps:
            print("- none")
        else:
            for row in focus_gaps:
                winners = ", ".join(list(row.get("winners") or []))
                print(
                    f"- {row.get('metric')}: winners={winners} "
                    f"gap={row.get('gap_to_best')} preference={row.get('preference')}"
                )

        print("")
        print(f"Competitors Beating {focus_agent} Most")
        if not top_threats:
            print("- none")
        else:
            for row in top_threats:
                print(
                    f"- {row.get('competitor')}: beat_metrics={row.get('metrics_beating_focus')} "
                    f"focus_beats={row.get('metrics_focus_beats')} "
                    f"composite_delta={row.get('composite_delta_vs_focus')}"
                )

    aggregate_focus = list(prediction.get("aggregate_predicted_focus") or [])
    aggregate_moves = list(prediction.get("aggregate_recommended_counter_moves") or [])
    print("")
    print("Prediction Evo Scope")
    if aggregate_focus:
        for row in aggregate_focus[:8]:
            print(f"- predicted area: {row.get('area')} (signals={row.get('count')})")
    else:
        print("- predicted area: none (not enough competitor version history yet)")
    if aggregate_moves:
        print("- recommended Thomas counter-moves:")
        for row in aggregate_moves[:8]:
            print(f"  - {row.get('move')} (signals={row.get('count')})")


def _render_markdown(result: Mapping[str, Any]) -> str:
    suite = dict(result.get("suite") or {})
    scoreboard = dict(result.get("scoreboard") or {})
    runtime_ranking = list(scoreboard.get("ranking") or [])
    focus = dict(result.get("focus") or {})
    gaps = list(focus.get("open_gaps") or [])
    pressure = dict(focus.get("competitor_pressure") or {})
    top_threats = list(pressure.get("top_threats") or [])
    prediction = dict(result.get("prediction_evo_scope") or {})
    contract = dict(result.get("test_suite_contract") or {})
    contract_summary = dict(contract.get("summary") or {})
    contract_runtime = dict(contract.get("runtime_metrics") or {})
    contract_catalog = dict((dict(contract.get("catalog") or {})).get("by_state") or {})
    dual_scoring = dict(result.get("overall_suite_scoreboard") or {})
    scoring_methodology = dict(dual_scoring.get("methodology") or {})
    ranking = list(dual_scoring.get("ranking") or [])
    runtime_map = {
        str(row.get("agent") or "").strip(): dict(row) for row in runtime_ranking if str(row.get("agent") or "").strip()
    }
    h2h = dict(dict(contract.get("scores") or {}).get("head_to_head") or {})
    token_efficiency = dict(dict(contract.get("scores") or {}).get("token_efficiency") or {})
    token_h2h = dict(token_efficiency.get("head_to_head") or {})
    token_ranking = list(token_efficiency.get("overall_ranking") or [])
    benchmark_program = dict(result.get("benchmark_program") or {})
    benchmark_ranking = list(benchmark_program.get("ranking") or [])
    agents = list(result.get("agents") or [])
    lines: list[str] = []
    lines.append(f"# Full Agent Comparison Suite ({suite.get('id')})")
    lines.append("")
    lines.append(f"- Computed at: `{result.get('computed_at_utc')}`")
    lines.append(f"- Config: `{suite.get('config_path')}`")
    policy = dict(suite.get("execution_policy") or {})
    if policy:
        lines.append(
            f"- Execution policy: quality_is_king=`{bool(policy.get('quality_is_king'))}`, "
            f"cycle_limit_disabled=`{bool(policy.get('cycle_limit_disabled'))}`"
        )
        if str(policy.get("stop_condition") or "").strip():
            lines.append(f"- Stop condition: `{policy.get('stop_condition')}`")
    lines.append("")
    lines.append("## Ranking")
    lines.append("")
    if scoring_methodology:
        tie_policy = str(h2h.get("tie_policy") or "half_point")
        lines.append(f"- Head-to-head method: `{scoring_methodology.get('head_to_head_score')}`")
        lines.append(f"- Token efficiency method: `{scoring_methodology.get('token_efficiency_score')}`")
        lines.append(f"- Overall suite method: `{scoring_methodology.get('overall_suite_score')}`")
        lines.append(f"- Lane suite method: `{scoring_methodology.get('lane_suite_scores')}`")
        lines.append("- Score math:")
        if tie_policy == "exclude":
            lines.append("- runtime head_to_head: `winner=1`, `ties_excluded`, `score=(points/counted_metrics)*100`")
        else:
            lines.append("- runtime head_to_head: `winner=1`, `tie=0.5`, `score=(points/counted_metrics)*100`")
        lines.append("- head_to_head_decisive: `winner=1`, `ties_excluded`, `score=(wins/non_tied_counted)*100`")
        lines.append(
            "- overall_suite: `(runtime_passed + catalog_passed) / (runtime_applicable + catalog_applicable) * 100`"
        )
        lines.append(
            "- lane_suite_scores: same formula as overall, filtered by `test_mode` (`quick`, `dynamic`, `human`)"
        )
        lines.append(
            "- token_efficiency: separate token-only scoring block, emitted only with token telemetry evidence"
        )
        lines.append("")
    for row in ranking:
        aid = str(row.get("agent") or "")
        runtime_row = dict(runtime_map.get(aid) or {})
        h2h_value = row.get("head_to_head_score")
        h2h_text = str(h2h_value) if _is_number(h2h_value) else "n/a"
        h2h_decisive_value = row.get("head_to_head_decisive_score")
        h2h_decisive_text = str(h2h_decisive_value) if _is_number(h2h_decisive_value) else "n/a"
        token_value = row.get("token_efficiency_score")
        token_text = str(token_value) if _is_number(token_value) else "n/a"
        lines.append(
            f"- #{row.get('overall_suite_rank')} `{row.get('agent')}`: overall_suite `{row.get('overall_suite_score')}`, capability `{row.get('overall_benchmark_capability_score')}`, "
            f"quick_suite `{row.get('quick_suite_score')}`, dynamic_suite `{row.get('dynamic_suite_score')}`, human_suite `{row.get('human_suite_score')}`, "
            f"runtime_rank `{runtime_row.get('rank')}`, head_to_head `{h2h_text}`, decisive_h2h `{h2h_decisive_text}`, token_efficiency `{token_text}`, "
            f"verdict `{row.get('governance_verdict')}`, runtime_wins `{runtime_row.get('wins')}`, "
            f"runtime_coverage `{round(float(runtime_row.get('coverage') or 0.0) * 100.0, 2)}%`"
        )
    lines.append("")
    lines.append("## Head-to-Head (1v1)")
    lines.append("")
    if bool(h2h.get("enabled")):
        tie_policy = str(h2h.get("tie_policy") or "half_point")
        lines.append(f"- Pair: `{h2h.get('agent_a')}` vs `{h2h.get('agent_b')}`")
        lines.append(
            f"- Scores: `{h2h.get('agent_a')}`=`{h2h.get('agent_a_score')}`, "
            f"`{h2h.get('agent_b')}`=`{h2h.get('agent_b_score')}` "
            f"(tie_policy `{tie_policy}`, counted_metrics `{h2h.get('counted_metrics')}`, "
            f"ties_counted `{h2h.get('ties')}`, ties_observed `{h2h.get('ties_observed')}`)"
        )
        lines.append(
            f"- Decisive (ties excluded): `{h2h.get('agent_a')}`=`{h2h.get('decisive_agent_a_score')}`, "
            f"`{h2h.get('agent_b')}`=`{h2h.get('decisive_agent_b_score')}` "
            f"(counted_metrics `{h2h.get('decisive_counted_metrics')}`)"
        )
        h2h_by_mode = dict(h2h.get("by_mode") or {})
        for mode in ("quick", "dynamic", "human"):
            mode_row = dict(h2h_by_mode.get(mode) or {})
            counted = int(mode_row.get("counted_metrics") or 0)
            if counted <= 0:
                continue
            lines.append(
                f"- By mode `{mode}`: `{h2h.get('agent_a')}`=`{mode_row.get('agent_a_score')}`, "
                f"`{h2h.get('agent_b')}`=`{mode_row.get('agent_b_score')}` "
                f"(counted_metrics `{counted}`, ties_counted `{mode_row.get('ties')}`, "
                f"ties_observed `{mode_row.get('ties_observed')}`)"
            )
    else:
        lines.append("- Not configured (use `--h2h-a` and `--h2h-b` for explicit 1v1).")
    lines.append("")
    lines.append("## Token Efficiency")
    lines.append("")
    lines.append(f"- Method: `{token_efficiency.get('methodology')}`")
    if bool(token_h2h.get("enabled")):
        lines.append(f"- Pair: `{token_h2h.get('agent_a')}` vs `{token_h2h.get('agent_b')}`")
        lines.append(
            f"- Scores: `{token_h2h.get('agent_a')}`=`{token_h2h.get('agent_a_score')}`, "
            f"`{token_h2h.get('agent_b')}`=`{token_h2h.get('agent_b_score')}` "
            f"(counted_metrics `{token_h2h.get('counted_metrics')}`, ties `{token_h2h.get('ties')}`)"
        )
    else:
        lines.append("- Pair: not configured.")
    for row in token_ranking[:6]:
        lines.append(
            f"- `#{row.get('token_efficiency_rank')}` `{row.get('agent')}`: "
            f"score `{row.get('token_efficiency_score')}`, "
            f"tokens_per_success `{row.get('effective_tokens_per_success')}`, "
            f"coverage `{row.get('telemetry_coverage')}`"
        )
    lines.append("")
    lines.append("## Benchmark Program")
    lines.append("")
    lines.append(f"- Program id: `{benchmark_program.get('id')}`")
    lane_weights = dict(benchmark_program.get("lane_weights") or {})
    if lane_weights:
        for lane in sorted(lane_weights.keys()):
            lines.append(f"- Lane weight `{lane}`: `{lane_weights[lane]}`")
    verdict_counts = dict(benchmark_program.get("verdict_counts") or {})
    if verdict_counts:
        for key in sorted(verdict_counts.keys()):
            lines.append(f"- Verdict `{key}`: `{verdict_counts[key]}`")
    for row in benchmark_ranking[:8]:
        lines.append(
            f"- `#{row.get('rank')}` `{row.get('agent')}`: capability `{row.get('overall_benchmark_capability_score')}`, "
            f"quick `{dict(row.get('lane_scores') or {}).get('quick', {}).get('score', 0.0)}`, "
            f"dynamic `{dict(row.get('lane_scores') or {}).get('dynamic', {}).get('score', 0.0)}`, "
            f"verdict `{row.get('governance_verdict')}`"
        )
    lines.append("")
    if contract:
        lines.append("## Full Coverage Contract")
        lines.append("")
        lines.append(
            f"- Tracked checks: `{contract_summary.get('tracked_total')}` "
            f"(implemented `{contract_summary.get('implemented_total')}`, planned `{contract_summary.get('planned_total')}`)"
        )
        lines.append(
            f"- Runtime metrics tracked: `{contract_runtime.get('total')}` "
            f"(focus data `{contract_runtime.get('with_focus_data')}`, comparable `{contract_runtime.get('comparable')}`)"
        )
        if contract_catalog:
            for key in sorted(contract_catalog.keys()):
                lines.append(f"- Catalog `{key}`: `{contract_catalog[key]}`")
        lines.append("")
    lines.append("## Agent Data Health")
    lines.append("")
    for agent in agents:
        errors = list(agent.get("errors") or [])
        version_info = dict(agent.get("version_info") or {})
        model_snapshot = dict(agent.get("model_snapshot") or {})
        lines.append(f"### {agent.get('id')}")
        lines.append(f"- Root: `{agent.get('root')}`")
        if version_info:
            head = str(version_info.get("local_head") or version_info.get("version") or "n/a")
            up = version_info.get("is_up_to_date")
            up_text = "yes" if up is True else ("no" if up is False else "unknown")
            lines.append(f"- Version: `{head}` (up_to_date={up_text})")
        if model_snapshot:
            model_value = str(model_snapshot.get("model") or model_snapshot.get("profile") or "n/a")
            lines.append(
                f"- Model snapshot: ok={bool(model_snapshot.get('ok'))}, day=`{model_snapshot.get('day_utc')}`, model=`{model_value}`"
            )
        lines.append(
            f"- Strict checks: {dict(agent.get('strict_checks') or {}).get('passed')} passed / {dict(agent.get('strict_checks') or {}).get('total')} total"
        )
        lines.append(f"- Benchmark runs used: {dict(agent.get('benchmark') or {}).get('runs_count')}")
        if errors:
            lines.append("- Errors:")
            for item in errors[:10]:
                lines.append(f"  - {item}")
        else:
            lines.append("- Errors: none")
        lines.append("")
    lines.append("## Focus Gaps")
    lines.append("")
    if not gaps:
        lines.append("- none")
    else:
        for row in gaps:
            winners = ", ".join(list(row.get("winners") or []))
            lines.append(
                f"- `{row.get('metric')}` ({row.get('category')}): winners `{winners}`, "
                f"gap `{row.get('gap_to_best')}`"
            )
    lines.append("")
    lines.append("## Competitor Pressure")
    lines.append("")
    if not top_threats:
        lines.append("- none")
    else:
        for row in top_threats:
            lines.append(
                f"- `{row.get('competitor')}`: beat_metrics `{row.get('metrics_beating_focus')}`, "
                f"focus_beats `{row.get('metrics_focus_beats')}`, "
                f"composite_delta `{row.get('composite_delta_vs_focus')}`"
            )
    lines.append("")
    lines.append("## Prediction Evo Scope")
    lines.append("")
    aggregate_focus = list(prediction.get("aggregate_predicted_focus") or [])
    aggregate_moves = list(prediction.get("aggregate_recommended_counter_moves") or [])
    if aggregate_focus:
        lines.append("### Predicted Next Competitor Focus")
        for row in aggregate_focus[:12]:
            lines.append(f"- `{row.get('area')}` ({row.get('count')} signals)")
    else:
        lines.append("- No competitor delta history yet.")
    lines.append("")
    if aggregate_moves:
        lines.append("### Recommended Thomas Counter-Moves")
        for row in aggregate_moves[:12]:
            lines.append(f"- {row.get('move')} ({row.get('count')} signals)")
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a comprehensive multi-agent comparison suite.")
    parser.add_argument(
        "--suite-config", default=str(DEFAULT_SUITE_CONFIG), help=f"Suite config path (default: {DEFAULT_SUITE_CONFIG})"
    )
    parser.add_argument("--focus-agent", default="thomas", help="Agent id to show open-gap list for.")
    parser.add_argument("--h2h-a", default="", help="Head-to-head agent A id (explicit 1v1 mode).")
    parser.add_argument("--h2h-b", default="", help="Head-to-head agent B id (explicit 1v1 mode).")
    parser.add_argument("--top-gaps", type=int, default=25, help="Maximum focus gaps to include.")
    parser.add_argument("--json", action="store_true", help="Print JSON result.")
    parser.add_argument("--write", action="store_true", help=f"Write JSON artifact (default: {DEFAULT_WRITE_PATH}).")
    parser.add_argument(
        "--write-path",
        default=str(DEFAULT_WRITE_PATH),
        help=f"JSON output path for --write (default: {DEFAULT_WRITE_PATH})",
    )
    parser.add_argument(
        "--write-md", action="store_true", help=f"Write markdown report (default: {DEFAULT_WRITE_MD_PATH})."
    )
    parser.add_argument(
        "--write-md-path",
        default=str(DEFAULT_WRITE_MD_PATH),
        help=f"Markdown output path for --write-md (default: {DEFAULT_WRITE_MD_PATH})",
    )
    parser.add_argument(
        "--test-suite-contract-path",
        default="",
        help=f"Override full coverage contract path (default from config or {DEFAULT_TEST_SUITE_CONTRACT_PATH}).",
    )
    parser.add_argument(
        "--registry-path",
        default=str(DEFAULT_REGISTRY_PATH),
        help=f"Competitor registry JSON path (default: {DEFAULT_REGISTRY_PATH})",
    )
    parser.add_argument(
        "--registry-md-path",
        default=str(DEFAULT_REGISTRY_MD_PATH),
        help=f"Competitor registry markdown path (default: {DEFAULT_REGISTRY_MD_PATH})",
    )
    parser.add_argument(
        "--no-registry-write", action="store_true", help="Disable competitor registry updates for this run."
    )
    return parser.parse_args(argv)


def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    suite_path = Path(str(args.suite_config))
    if not suite_path.is_absolute():
        suite_path = (ROOT / suite_path).resolve()
    suite_config = load_suite_config(suite_path)
    if str(args.test_suite_contract_path or "").strip():
        suite_config = dict(suite_config)
        suite_config["test_suite_contract_path"] = str(args.test_suite_contract_path).strip()
    if str(args.h2h_a or "").strip() and str(args.h2h_b or "").strip():
        suite_config = dict(suite_config)
        suite_config["head_to_head_pair"] = [str(args.h2h_a).strip(), str(args.h2h_b).strip()]
    head_to_head_pair = [
        str(item).strip() for item in (suite_config.get("head_to_head_pair") or []) if str(item).strip()
    ]
    if len(head_to_head_pair) != 2:
        head_to_head_pair = []

    out_path = Path(str(args.write_path))
    if not out_path.is_absolute():
        out_path = (ROOT / out_path).resolve()
    out_md = Path(str(args.write_md_path))
    if not out_md.is_absolute():
        out_md = (ROOT / out_md).resolve()
    registry_path = Path(str(args.registry_path))
    if not registry_path.is_absolute():
        registry_path = (ROOT / registry_path).resolve()
    registry_md_path = Path(str(args.registry_md_path))
    if not registry_md_path.is_absolute():
        registry_md_path = (ROOT / registry_md_path).resolve()
    previous_registry = load_registry(registry_path)
    previous_competitors = dict(previous_registry.get("competitors") or {})

    result = build_suite_result(
        suite_config=suite_config,
        suite_path=suite_path,
        focus_agent=str(args.focus_agent or "").strip(),
        top_gaps=max(0, int(args.top_gaps)),
        head_to_head_pair=head_to_head_pair,
        previous_registry_competitors=previous_competitors,
    )
    required_model_failures: list[str] = []
    for agent in list(result.get("agents") or []):
        aid = str(agent.get("id") or "").strip()
        snapshot = dict(agent.get("model_snapshot") or {})
        if bool(snapshot.get("required")) and not bool(snapshot.get("ok")):
            required_model_failures.append(f"{aid}: {snapshot.get('error') or 'required model snapshot missing'}")
    result["validation"] = {"required_model_snapshot_failures": required_model_failures}

    if bool(args.write):
        _write_json(out_path, result)
    if bool(args.write_md):
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(_render_markdown(result), encoding="utf-8")

    if not bool(args.no_registry_write):
        _update_competitor_registry(
            result=result,
            registry_path=registry_path,
            registry_md_path=registry_md_path,
            result_json_path=(out_path if bool(args.write) else None),
            result_md_path=(out_md if bool(args.write_md) else None),
        )

    if bool(args.json):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_human(result)
        if required_model_failures:
            print("")
            print("Model Snapshot Validation")
            for row in required_model_failures:
                print(f"- {row}")

    return 2 if required_model_failures else 0


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
