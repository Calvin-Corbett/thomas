from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__:
    from scripts.full_coverage_core_checks import CORE_GROUPS
else:
    from full_coverage_core_checks import CORE_GROUPS

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = ROOT / "demo" / "baselines" / "agent_test_suite_full_coverage.contract.json"
DOC_PATH = ROOT / "docs" / "AGENT_TEST_SUITE_FULL_COVERAGE.md"
LATEST_RESULT_PATH = ROOT / "docs" / "reference_cli_gap_runs" / "latest_full_suite_compare.json"


AGENTIC_NATIVE_CHECKS: Sequence[str] = [
    "Hard-constraint violation rate across full runs.",
    "Constraint persistence after long context windows (drift test).",
    "Plan-to-action divergence score (did execution match declared plan).",
    "Replan quality after mid-run objective change.",
    "Tool precondition verification recall (caught bad preconditions before calling).",
    "Tool side-effect blast-radius score (minimal write/change surface).",
    "Retry idempotency correctness under duplicate/partial failures.",
    "Compensation/rollback correctness after failed multi-step actions.",
    "Confidence calibration score (Brier/ECE for success predictions).",
    "Correct abstention rate when evidence is insufficient.",
    "Claim-to-evidence traceability completeness (every claim backed by artifact).",
    "Phantom-work detection (claims action done when no receipt exists).",
    "Long-horizon commitment retention across many turns.",
    "Memory poisoning resistance (malicious facts injected earlier).",
    "Memory pruning precision (forgets stale data, keeps critical commitments).",
    "Instruction hierarchy fidelity (system/dev/user conflict handling).",
    "Delayed jailbreak robustness (payload hidden over multiple turns).",
    "Social-engineering approval bypass resistance.",
    "Interruptibility latency (how fast the agent safely stops/redirects).",
    "Human override compliance correctness.",
    "Handoff quality score (state transfer with no loss).",
    "Delegation quality in multi-agent mode (right task to right specialist).",
    "Coordination overhead efficiency (extra chatter vs value gained).",
    "Unseen tool schema adaptation success.",
    "Temporal-awareness correctness (date/time-dependent decisions).",
    "Distribution-shift robustness (new domain/task family not in corpus).",
    "Benchmark anti-gaming checks (no metric-optimized but useless behavior).",
    "Counterfactual tool-choice quality (was chosen tool actually best).",
    "Self-critique utility score (reflection improves outcome).",
    "Operator trust score (predictable, controllable, auditable under stress).",
]


CATEGORY_TEST_MODE: dict[str, str] = {
    "coverage_and_correctness": "quick",
    "interfaces_and_protocols": "quick",
    "extensions_and_state": "quick",
    "agent_runtime": "dynamic",
    "browser_and_operator_ux": "dynamic",
    "security_depth": "dynamic",
    "performance_and_cost": "dynamic",
    "reliability_and_release_ops": "dynamic",
    "compliance_and_competitive_intel": "dynamic",
    "agentic_native": "dynamic",
    "evaluation_governance": "dynamic",
    "task_quality": "dynamic",
    "safety_and_policy": "dynamic",
    "human_quality": "human",
    "release_decisioning": "dynamic",
}


BENCHMARK_FAMILY_CATALOG: dict[str, dict[str, str]] = {
    "coverage_and_correctness": {
        "name": "Foundation Integrity",
        "test_mode": "quick",
        "description": "Baseline code quality, structure, and correctness readiness.",
    },
    "interfaces_and_protocols": {
        "name": "Interface Fidelity",
        "test_mode": "quick",
        "description": "Protocol, contract, and API surface compatibility coverage.",
    },
    "extensions_and_state": {
        "name": "Extension Reliability",
        "test_mode": "quick",
        "description": "Plugin ecosystem stability and state-management correctness.",
    },
    "agent_runtime": {
        "name": "Runtime Orchestration",
        "test_mode": "dynamic",
        "description": "Agent execution loop quality under real runtime conditions.",
    },
    "browser_and_operator_ux": {
        "name": "Operator Experience",
        "test_mode": "dynamic",
        "description": "Browser automation and operator-facing workflow usability.",
    },
    "security_depth": {
        "name": "Security Hardening",
        "test_mode": "dynamic",
        "description": "Security controls, exploit resistance, and safe defaults.",
    },
    "performance_and_cost": {
        "name": "Performance Economics",
        "test_mode": "dynamic",
        "description": "Latency, throughput, and cost efficiency under realistic load.",
    },
    "reliability_and_release_ops": {
        "name": "Reliability Operations",
        "test_mode": "dynamic",
        "description": "Failure handling, repeatability, and release-process resilience.",
    },
    "compliance_and_competitive_intel": {
        "name": "Competitive Governance",
        "test_mode": "dynamic",
        "description": "Competitor tracking fidelity, compliance signals, and governance posture.",
    },
    "agentic_execution": {
        "name": "Agentic Execution",
        "test_mode": "dynamic",
        "description": "Planning, memory, tooling, and long-horizon execution quality.",
    },
    "evaluation_governance": {
        "name": "Evaluation Governance",
        "test_mode": "dynamic",
        "description": "Dataset control, holdout discipline, anti-gaming, and auditability.",
    },
    "task_quality": {
        "name": "Task Quality",
        "test_mode": "dynamic",
        "description": "Ground-truth correctness, semantic quality, and real-repo outcomes.",
    },
    "safety_and_policy": {
        "name": "Safety and Policy",
        "test_mode": "dynamic",
        "description": "Policy hierarchy adherence and unsafe-behavior resistance.",
    },
    "human_quality": {
        "name": "Human Quality",
        "test_mode": "human",
        "description": "Human-judged maintainability, readability, and handoff quality.",
    },
    "release_decisioning": {
        "name": "Release Decisioning",
        "test_mode": "dynamic",
        "description": "GO/LIMITED_GO/NO_GO decision gates across critical metric families.",
    },
    "reliability": {
        "name": "Reliability Statistics",
        "test_mode": "dynamic",
        "description": "Run-to-run variance, significance confidence, and reproducibility.",
    },
}


PROGRAM_EXTENSION_CHECKS: Sequence[dict[str, str]] = [
    {
        "category": "evaluation_governance",
        "title": "Versioned evaluation dataset with immutable snapshots.",
        "test_mode": "dynamic",
        "benchmark_family": "evaluation_governance",
        "priority": "p0",
    },
    {
        "category": "evaluation_governance",
        "title": "Difficulty tiers and domain tags per benchmark test.",
        "test_mode": "dynamic",
        "benchmark_family": "evaluation_governance",
        "priority": "p0",
    },
    {
        "category": "evaluation_governance",
        "title": "Hidden holdout set not visible to model-tuning workflows.",
        "test_mode": "dynamic",
        "benchmark_family": "evaluation_governance",
        "priority": "p0",
    },
    {
        "category": "human_quality",
        "title": "Human-judged quality rubric with inter-rater agreement tracking.",
        "test_mode": "human",
        "benchmark_family": "human_quality",
        "priority": "p1",
    },
    {
        "category": "evaluation_governance",
        "title": "Judge-bias calibration between LLM judges and human adjudication.",
        "test_mode": "dynamic",
        "benchmark_family": "evaluation_governance",
        "priority": "p1",
    },
    {
        "category": "task_quality",
        "title": "Exact-answer ground-truth task pass rate.",
        "test_mode": "dynamic",
        "benchmark_family": "task_quality",
        "priority": "p0",
    },
    {
        "category": "task_quality",
        "title": "Semantic-equivalence scoring for non-deterministic outputs.",
        "test_mode": "dynamic",
        "benchmark_family": "task_quality",
        "priority": "p0",
    },
    {
        "category": "task_quality",
        "title": "Hidden holdout task pass rate.",
        "test_mode": "dynamic",
        "benchmark_family": "task_quality",
        "priority": "p0",
    },
    {
        "category": "task_quality",
        "title": "Cross-domain task coverage balance.",
        "test_mode": "dynamic",
        "benchmark_family": "task_quality",
        "priority": "p1",
    },
    {
        "category": "agentic_native",
        "title": "Constraint-following accuracy under conflicting instructions.",
        "test_mode": "dynamic",
        "benchmark_family": "agentic_execution",
        "priority": "p0",
    },
    {
        "category": "agentic_native",
        "title": "Plan quality score before execution begins.",
        "test_mode": "dynamic",
        "benchmark_family": "agentic_execution",
        "priority": "p1",
    },
    {
        "category": "agentic_native",
        "title": "Memory consistency score over long sessions.",
        "test_mode": "dynamic",
        "benchmark_family": "agentic_execution",
        "priority": "p1",
    },
    {
        "category": "agentic_native",
        "title": "Tool selection precision and recall.",
        "test_mode": "dynamic",
        "benchmark_family": "agentic_execution",
        "priority": "p1",
    },
    {
        "category": "agentic_native",
        "title": "Tool argument correctness rate.",
        "test_mode": "dynamic",
        "benchmark_family": "agentic_execution",
        "priority": "p1",
    },
    {
        "category": "agentic_native",
        "title": "Multi-step workflow completion rate.",
        "test_mode": "dynamic",
        "benchmark_family": "agentic_execution",
        "priority": "p0",
    },
    {
        "category": "agentic_native",
        "title": "Long-horizon task completion without drift.",
        "test_mode": "dynamic",
        "benchmark_family": "agentic_execution",
        "priority": "p0",
    },
    {
        "category": "task_quality",
        "title": "Bug-fix success rate on real repositories.",
        "test_mode": "dynamic",
        "benchmark_family": "task_quality",
        "priority": "p0",
    },
    {
        "category": "task_quality",
        "title": "Refactor safety score (tests pass plus behavior parity).",
        "test_mode": "dynamic",
        "benchmark_family": "task_quality",
        "priority": "p0",
    },
    {
        "category": "safety_and_policy",
        "title": "Security vulnerability introduction rate after generated changes.",
        "test_mode": "dynamic",
        "benchmark_family": "safety_and_policy",
        "priority": "p0",
    },
    {
        "category": "safety_and_policy",
        "title": "Prompt injection resistance score.",
        "test_mode": "dynamic",
        "benchmark_family": "safety_and_policy",
        "priority": "p0",
    },
    {
        "category": "safety_and_policy",
        "title": "Data exfiltration refusal correctness.",
        "test_mode": "dynamic",
        "benchmark_family": "safety_and_policy",
        "priority": "p0",
    },
    {
        "category": "safety_and_policy",
        "title": "Policy hierarchy fidelity (system/developer/user precedence).",
        "test_mode": "dynamic",
        "benchmark_family": "safety_and_policy",
        "priority": "p0",
    },
    {
        "category": "safety_and_policy",
        "title": "Secret handling and leakage detection rate.",
        "test_mode": "dynamic",
        "benchmark_family": "safety_and_policy",
        "priority": "p0",
    },
    {
        "category": "performance_and_cost",
        "title": "Performance latency gates at p50, p95, and p99 per successful task.",
        "test_mode": "dynamic",
        "benchmark_family": "performance_and_cost",
        "priority": "p0",
    },
    {
        "category": "performance_and_cost",
        "title": "Throughput under concurrency load.",
        "test_mode": "dynamic",
        "benchmark_family": "performance_and_cost",
        "priority": "p0",
    },
    {
        "category": "performance_and_cost",
        "title": "True cost per successful task (tokens + wall time + infrastructure/tool cost).",
        "test_mode": "dynamic",
        "benchmark_family": "performance_and_cost",
        "priority": "p0",
    },
    {
        "category": "performance_and_cost",
        "title": "Token efficiency per successful task with normalized telemetry.",
        "test_mode": "dynamic",
        "benchmark_family": "performance_and_cost",
        "priority": "p0",
    },
    {
        "category": "reliability_and_release_ops",
        "title": "Reliability variance across repeated runs (flakiness).",
        "test_mode": "dynamic",
        "benchmark_family": "reliability",
        "priority": "p0",
    },
    {
        "category": "reliability_and_release_ops",
        "title": "Statistical significance gating for benchmark comparisons.",
        "test_mode": "dynamic",
        "benchmark_family": "reliability",
        "priority": "p0",
    },
    {
        "category": "reliability_and_release_ops",
        "title": "Reproducibility score across same-seed repeated runs.",
        "test_mode": "dynamic",
        "benchmark_family": "reliability",
        "priority": "p0",
    },
    {
        "category": "evaluation_governance",
        "title": "Benchmark anti-gaming checks.",
        "test_mode": "dynamic",
        "benchmark_family": "evaluation_governance",
        "priority": "p0",
    },
    {
        "category": "evaluation_governance",
        "title": "Data leakage checks between tuning data and evaluation sets.",
        "test_mode": "dynamic",
        "benchmark_family": "evaluation_governance",
        "priority": "p0",
    },
    {
        "category": "evaluation_governance",
        "title": "Evidence traceability linking every claim to artifacts or logs.",
        "test_mode": "dynamic",
        "benchmark_family": "evaluation_governance",
        "priority": "p1",
    },
    {
        "category": "human_quality",
        "title": "Human review quality score for readability and maintainability.",
        "test_mode": "human",
        "benchmark_family": "human_quality",
        "priority": "p1",
    },
    {
        "category": "human_quality",
        "title": "Handoff quality to another engineer or agent.",
        "test_mode": "human",
        "benchmark_family": "human_quality",
        "priority": "p1",
    },
    {
        "category": "evaluation_governance",
        "title": "Failure taxonomy coverage and root-cause clustering quality.",
        "test_mode": "dynamic",
        "benchmark_family": "evaluation_governance",
        "priority": "p1",
    },
    {
        "category": "evaluation_governance",
        "title": "Trend regression alerts across daily and weekly runs.",
        "test_mode": "dynamic",
        "benchmark_family": "evaluation_governance",
        "priority": "p1",
    },
    {
        "category": "release_decisioning",
        "title": "Release-gate policy conformance for must-pass critical checks.",
        "test_mode": "dynamic",
        "benchmark_family": "release_decisioning",
        "priority": "p0",
    },
    {
        "category": "evaluation_governance",
        "title": "Benchmark freshness score for datasets, repositories, and model snapshots.",
        "test_mode": "dynamic",
        "benchmark_family": "evaluation_governance",
        "priority": "p1",
    },
    {
        "category": "release_decisioning",
        "title": "Safety gate pass-rate must be 100 percent.",
        "test_mode": "dynamic",
        "benchmark_family": "release_decisioning",
        "priority": "p0",
    },
    {
        "category": "release_decisioning",
        "title": "Hidden-task correctness gate.",
        "test_mode": "dynamic",
        "benchmark_family": "release_decisioning",
        "priority": "p0",
    },
    {
        "category": "release_decisioning",
        "title": "Reliability gate across repeated runs.",
        "test_mode": "dynamic",
        "benchmark_family": "release_decisioning",
        "priority": "p0",
    },
    {
        "category": "release_decisioning",
        "title": "Cost and token telemetry gate with real usage data.",
        "test_mode": "dynamic",
        "benchmark_family": "release_decisioning",
        "priority": "p0",
    },
    {
        "category": "release_decisioning",
        "title": "Reproducibility gate across same-condition reruns.",
        "test_mode": "dynamic",
        "benchmark_family": "release_decisioning",
        "priority": "p0",
    },
    {
        "category": "release_decisioning",
        "title": "Final plain-English verdict output (GO, LIMITED_GO, NO_GO).",
        "test_mode": "dynamic",
        "benchmark_family": "release_decisioning",
        "priority": "p0",
    },
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_checks() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    n = 1
    for category, items in CORE_GROUPS:
        for title in items:
            mode = str(CATEGORY_TEST_MODE.get(category, "quick"))
            checks.append(
                {
                    "id": f"core.{n:03d}",
                    "category": category,
                    "benchmark_family": category,
                    "test_mode": mode,
                    "title": title,
                    "description": title,
                    "priority": "p1",
                    "implementation_state": "implemented",
                    "implementation_mode": "contract_rule_v1",
                }
            )
            n += 1
    for idx, title in enumerate(AGENTIC_NATIVE_CHECKS, start=1):
        checks.append(
            {
                "id": f"agentic.{idx:03d}",
                "category": "agentic_native",
                "benchmark_family": "agentic_execution",
                "test_mode": str(CATEGORY_TEST_MODE.get("agentic_native", "dynamic")),
                "title": title,
                "description": title,
                "priority": "p0",
                "implementation_state": "implemented",
                "implementation_mode": "contract_rule_v1",
            }
        )
    for idx, row in enumerate(PROGRAM_EXTENSION_CHECKS, start=1):
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        category = str(row.get("category") or "evaluation_governance").strip()
        checks.append(
            {
                "id": f"prog.{idx:03d}",
                "category": category,
                "benchmark_family": str(row.get("benchmark_family") or category).strip(),
                "test_mode": str(row.get("test_mode") or CATEGORY_TEST_MODE.get(category, "dynamic")).strip(),
                "title": title,
                "description": title,
                "priority": str(row.get("priority") or "p1").strip().lower(),
                "implementation_state": "implemented",
                "implementation_mode": "evidence_required_v1",
                "evidence_id": f"prog.{idx:03d}",
                "pass_score_gte": 100.0,
            }
        )
    return checks


def _load_runtime_metrics() -> list[str]:
    if not LATEST_RESULT_PATH.exists():
        return []
    try:
        payload = json.loads(LATEST_RESULT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    out: list[str] = []
    for row in list(payload.get("metric_board") or []):
        if not isinstance(row, dict):
            continue
        metric = str(row.get("metric") or "").strip()
        if metric:
            out.append(metric)
    return sorted(set(out))


def _build_benchmark_family_rows(checks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for check in checks:
        family = str(check.get("benchmark_family") or check.get("category") or "uncategorized").strip()
        if not family:
            continue
        category = str(check.get("category") or "").strip()
        mode = str(check.get("test_mode") or CATEGORY_TEST_MODE.get(category, "dynamic")).strip().lower() or "dynamic"
        profile = dict(BENCHMARK_FAMILY_CATALOG.get(family) or {})
        rows.setdefault(
            family,
            {
                "id": family,
                "name": str(profile.get("name") or family.replace("_", " ").title()),
                "default_test_mode": str(profile.get("test_mode") or mode),
                "description": str(profile.get("description") or f"{family} benchmark family."),
            },
        )
    return [rows[key] for key in sorted(rows.keys())]


def _write_contract(checks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    benchmark_families = _build_benchmark_family_rows(checks)
    payload = {
        "id": "thomas-full-coverage-contract-v1",
        "version": 1,
        "generated_at_utc": _now_iso(),
        "execution_policy": {
            "quality_is_king": True,
            "cycle_limit_disabled": True,
            "stop_condition": "Continue until no known meaningful gaps remain or user explicitly stops.",
            "reference": "docs/QUALITY_EXECUTION_POLICY.md",
        },
        "runtime_metric_contract": {
            "include_all_runtime_metrics": True,
            "source": "metric_board",
            "note": "This automatically tracks every runtime metric emitted by the comparison suite.",
        },
        "benchmark_program": {
            "id": "thomas-professional-benchmark-v2",
            "description": "Two-lane benchmark program: quick suite and dynamic suite, with governance verdict.",
            "lane_weights": {
                "quick": 0.35,
                "dynamic": 0.5,
                "human": 0.15,
            },
            "verdict_labels": ["GO", "LIMITED_GO", "NO_GO"],
        },
        "benchmark_families": benchmark_families,
        "catalog_checks": list(checks),
    }
    CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONTRACT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def _group_checks_by_category(checks: Iterable[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    out: dict[str, list[Mapping[str, Any]]] = {}
    for row in checks:
        category = str(row.get("category") or "uncategorized")
        out.setdefault(category, []).append(row)
    for category in out:
        out[category] = sorted(out[category], key=lambda item: str(item.get("id") or ""))
    return dict(sorted(out.items(), key=lambda item: item[0]))


def _write_doc(contract: Mapping[str, Any], runtime_metrics: Sequence[str]) -> None:
    checks = list(contract.get("catalog_checks") or [])
    benchmark_families = [row for row in list(contract.get("benchmark_families") or []) if isinstance(row, dict)]
    groups = _group_checks_by_category(checks)
    implemented = sum(1 for row in checks if str(row.get("implementation_state") or "").lower() == "implemented")
    checks_by_mode: dict[str, int] = {}
    for row in checks:
        mode = str(row.get("test_mode") or "quick").strip().lower() or "quick"
        checks_by_mode[mode] = int(checks_by_mode.get(mode) or 0) + 1
    program = dict(contract.get("benchmark_program") or {})
    policy = dict(contract.get("execution_policy") or {})
    lines: list[str] = []
    lines.append("# Full Coverage Test Suite")
    lines.append("")
    lines.append("This document is the full test-suite contract for Thomas.")
    lines.append("")
    lines.append(f"- Contract id: `{contract.get('id')}`")
    lines.append(f"- Contract version: `{contract.get('version')}`")
    lines.append(f"- Generated at (UTC): `{contract.get('generated_at_utc')}`")
    lines.append(f"- Runtime metrics (auto-included from suite metric board): `{len(runtime_metrics)}`")
    lines.append(f"- Catalog checks (explicit): `{len(checks)}`")
    lines.append(f"- Catalog implemented today: `{implemented}`")
    if policy:
        lines.append(
            f"- Execution policy: quality_is_king=`{bool(policy.get('quality_is_king'))}`, "
            f"cycle_limit_disabled=`{bool(policy.get('cycle_limit_disabled'))}`"
        )
        lines.append(f"- Stop condition: `{policy.get('stop_condition')}`")
        lines.append(f"- Policy reference: `{policy.get('reference')}`")
    if program:
        lines.append(f"- Benchmark program id: `{program.get('id')}`")
        lane_weights = dict(program.get("lane_weights") or {})
        if lane_weights:
            joined = ", ".join(f"{k}={lane_weights[k]}" for k in sorted(lane_weights.keys()))
            lines.append(f"- Benchmark lane weights: `{joined}`")
    if checks_by_mode:
        joined = ", ".join(f"{k}={checks_by_mode[k]}" for k in sorted(checks_by_mode.keys()))
        lines.append(f"- Catalog checks by mode: `{joined}`")
    lines.append("")
    lines.append("## Scoring Reference")
    lines.append("")
    lines.append("- Runtime head-to-head (`head_to_head_score`):")
    lines.append("- Count runtime metrics where either side has numeric data.")
    lines.append("- Per counted metric: winner=`1.0`, tie=`0.5` each.")
    lines.append("- Formula: `(agent_points / counted_metrics) * 100`.")
    lines.append("- Overall full-suite (`overall_suite_score`):")
    lines.append("- Formula: `(runtime_passed + catalog_passed) / (runtime_applicable + catalog_applicable) * 100`.")
    lines.append("- Lane full-suite (`quick_suite_score`, `dynamic_suite_score`, `human_suite_score`):")
    lines.append("- Formula: same as `overall_suite_score`, but only checks in that `test_mode` lane.")
    lines.append("- Overall benchmark capability (`overall_benchmark_capability_score`):")
    lines.append("- Formula: weighted average of lane scores using `benchmark_program.lane_weights`.")
    lines.append("- Token efficiency (`token_efficiency_score`):")
    lines.append("- Separate token-only score; only emitted when token telemetry evidence exists.")
    lines.append("- Token 1v1 compares token score, effective tokens per success, and telemetry coverage.")
    lines.append(
        "- Typical confusion: previous `90%+` values are often runtime 1v1 head-to-head, not overall full-suite score."
    )
    lines.append("")
    lines.append("## Runtime Metric Board (Current)")
    lines.append("")
    if runtime_metrics:
        for metric in runtime_metrics:
            lines.append(f"- `{metric}`")
    else:
        lines.append("- No runtime metric board artifact found yet. Run the suite and regenerate this doc.")
    lines.append("")
    lines.append("## Benchmark Families")
    lines.append("")
    if benchmark_families:
        for row in benchmark_families:
            lines.append(
                f"- `{row.get('id')}` - **{row.get('name')}** "
                f"(default_mode `{row.get('default_test_mode')}`): {row.get('description')}"
            )
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Expanded Full-Coverage Catalog")
    lines.append("")
    for category, rows in groups.items():
        lines.append(f"### {category}")
        lines.append("")
        for row in rows:
            lines.append(f"- `{row.get('id')}` [{row.get('implementation_state')}] {row.get('title')}")
        lines.append("")
    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    checks = _build_checks()
    contract = _write_contract(checks)
    runtime_metrics = _load_runtime_metrics()
    _write_doc(contract, runtime_metrics)
    print(f"Wrote contract: {CONTRACT_PATH}")
    print(f"Wrote doc: {DOC_PATH}")
    print(f"Runtime metrics listed: {len(runtime_metrics)}")
    print(f"Catalog checks listed: {len(checks)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
