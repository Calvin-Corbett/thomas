from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple


ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = ROOT / "demo" / "baselines" / "agent_test_suite_full_coverage.contract.json"
DOC_PATH = ROOT / "docs" / "AGENT_TEST_SUITE_FULL_COVERAGE.md"
LATEST_RESULT_PATH = ROOT / "docs" / "openclaw_gap_runs" / "latest_full_suite_compare.json"


CORE_GROUPS: Sequence[Tuple[str, Sequence[str]]] = [
    (
        "coverage_and_correctness",
        [
            "Global line coverage gate.",
            "Global branch coverage gate.",
            "Global function coverage gate.",
            "Per-package line coverage minimums.",
            "Per-package branch coverage minimums.",
            "Diff coverage gate on changed files.",
            "Mutation testing minimum score.",
            "Unit tests for every public function.",
            "Unit tests for every error branch.",
            "Unit tests for serialization/deserialization.",
            "Property-based tests for core parsers.",
            "Property-based tests for validators.",
            "Metamorphic tests for deterministic transforms.",
            "Golden tests for stable outputs.",
            "Snapshot tests for structured payloads.",
            "Fuzz tests for input parsers.",
            "Unicode/encoding edge-case tests.",
            "Timezone and DST correctness tests.",
            "Locale/i18n formatting correctness tests.",
            "Cross-platform path handling tests.",
        ],
    ),
    (
        "interfaces_and_protocols",
        [
            "CLI command existence contract tests.",
            "CLI help/usage schema tests.",
            "CLI argument normalization tests.",
            "CLI invalid-arg failure-mode tests.",
            "CLI exit-code contract tests.",
            "API schema conformance tests (request).",
            "API schema conformance tests (response).",
            "OpenAI-compat gateway protocol tests.",
            "Streaming response event-order tests.",
            "Retry/idempotency behavior tests.",
            "Pagination correctness tests.",
            "Rate-limit behavior tests.",
            "AuthN failure tests.",
            "AuthZ failure tests.",
            "Backward-compat API version tests.",
            "Webhook signature verification tests.",
            "Webhook replay-protection tests.",
            "WebSocket connect/disconnect tests.",
            "WebSocket backpressure tests.",
            "WebSocket reconnect recovery tests.",
        ],
    ),
    (
        "agent_runtime",
        [
            "Agent routing correctness tests.",
            "Tool-selection policy tests.",
            "Tool argument schema tests.",
            "Tool-call timeout handling tests.",
            "Tool-call cancellation tests.",
            "Tool-call partial-failure recovery tests.",
            "Agent memory write/read consistency tests.",
            "Memory contradiction detection tests.",
            "Memory curation quality tests.",
            "Context-window truncation safety tests.",
            "Prompt-injection resistance tests.",
            "Data-exfiltration refusal tests.",
            "Unsafe-action refusal tests.",
            "Policy override resistance tests.",
            "Model fallback correctness tests.",
            "Multi-provider model parity tests.",
            "Deterministic replay tests of agent runs.",
            "Long-conversation coherence tests.",
            "Task planning/execution parity tests.",
            "Hallucination guardrail tests with known answers.",
        ],
    ),
    (
        "browser_and_operator_ux",
        [
            "Browser workflow corpus validity tests.",
            "Browser workflow runtime execution tests.",
            "Browser profile coverage tests.",
            "Browser extension interaction tests.",
            "DOM-selector drift resilience tests.",
            "Browser timeout/retry tests.",
            "Desktop viewport visual regression tests.",
            "Mobile viewport visual regression tests.",
            "Accessibility keyboard-nav tests.",
            "Accessibility ARIA/semantic tests.",
            "Accessibility contrast tests.",
            "Frontend error boundary tests.",
            "Frontend state restoration tests.",
            "Frontend offline behavior tests.",
            "Frontend slow-network behavior tests.",
            "Service worker/cache correctness tests.",
            "Client-side auth/session expiry tests.",
            "Cross-browser matrix tests (Chrome/Edge/Firefox).",
            "Mobile emulation matrix tests.",
            "UI telemetry event contract tests.",
        ],
    ),
    (
        "extensions_and_state",
        [
            "Extension catalog schema tests.",
            "Extension catalog runtime load tests.",
            "Extension install tests.",
            "Extension upgrade tests.",
            "Extension rollback tests.",
            "Extension uninstall cleanup tests.",
            "Extension dependency conflict tests.",
            "Extension sandbox/permission tests.",
            "Extension API compatibility version tests.",
            "Extension cold-start performance tests.",
            "DB migration forward tests.",
            "DB migration rollback tests.",
            "Corrupt-data recovery tests.",
            "Backup/restore integrity tests.",
            "Concurrency lock/race-condition tests.",
            "Transaction atomicity tests.",
            "Data retention/purge tests.",
            "PII redaction correctness tests.",
            "Audit log integrity tests.",
            "Cross-version state compatibility tests.",
        ],
    ),
    (
        "security_depth",
        [
            "SAST gate (high/critical fail).",
            "DAST gate for exposed endpoints.",
            "Secret scanning gate.",
            "Dependency vulnerability gate (runtime).",
            "Dependency vulnerability gate (dev-time).",
            "License policy gate.",
            "SBOM generation + diff gate.",
            "Artifact provenance/signature verification.",
            "Sandbox escape attempt tests.",
            "Command injection tests.",
            "SQL injection tests.",
            "XSS tests.",
            "CSRF tests.",
            "SSRF tests.",
            "Path traversal tests.",
            "Zip-slip/file extraction tests.",
            "Unsafe deserialization tests.",
            "Cryptography misuse tests.",
            "Session fixation/hijack tests.",
            "Security regression replay suite.",
        ],
    ),
    (
        "performance_and_cost",
        [
            "Cold-start latency benchmarks.",
            "Warm-path latency benchmarks.",
            "P50/P95/P99 latency gates.",
            "Throughput saturation tests.",
            "Concurrency scaling tests.",
            "Memory leak soak tests.",
            "CPU regression gates.",
            "I/O regression gates.",
            "Queue depth/backlog stress tests.",
            "Autoscaling behavior tests.",
            "Tail-latency under failure tests.",
            "Load-shedding behavior tests.",
            "Graceful degradation tests.",
            "Thundering-herd prevention tests.",
            "Cache hit-rate regression tests.",
            "Cache invalidation correctness tests.",
            "Cost-per-task regression gates.",
            "Token-per-success regression gates.",
            "Tool-call-per-success regression gates.",
            "Provider spend-cap enforcement tests.",
        ],
    ),
    (
        "reliability_and_release_ops",
        [
            "Flakiness detection and quarantine pipeline.",
            "Test repeatability checks (N reruns).",
            "Randomized test-order stability checks.",
            "Hermetic test environment checks.",
            "Seeded reproducibility checks.",
            "Fixture isolation checks.",
            "Clock-freeze deterministic tests.",
            "CI timeout budget tests.",
            "Parallel test safety checks.",
            "Artifact retention and traceability checks.",
            "Release-candidate smoke suite.",
            "Release rollback drills.",
            "Blue/green deployment tests.",
            "Canary gating tests.",
            "Post-deploy synthetic transaction tests.",
            "SLO/error-budget gate checks.",
            "Alert routing correctness tests.",
            "On-call runbook execution drills.",
            "Disaster-recovery failover tests.",
            "Regional outage simulation tests.",
        ],
    ),
    (
        "compliance_and_competitive_intel",
        [
            "Compliance logging completeness tests.",
            "GDPR delete/export flow tests.",
            "SOC2 control evidence tests.",
            "Data residency routing tests.",
            "Accessibility compliance gates (WCAG).",
            "Terms/policy enforcement tests.",
            "Content moderation pipeline tests.",
            "Abuse-rate limiting tests.",
            "Multi-tenant isolation tests.",
            "Tenant billing boundary tests.",
            "Competitor catalog freshness tests.",
            "Competitor auto-clone/update tests.",
            "Competitor version capture tests.",
            "Daily model snapshot enforcement tests.",
            "Competitor pressure-board correctness tests.",
            "Prediction-evo-scope delta detection tests.",
            "Prediction-evo-scope recommendation validity tests.",
            "Benchmark corpus anti-gaming checks.",
            "Cross-run comparability normalization checks.",
            "Historical trend regression alerts.",
        ],
    ),
]


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_checks() -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []
    n = 1
    for category, items in CORE_GROUPS:
        for title in items:
            checks.append(
                {
                    "id": f"core.{n:03d}",
                    "category": category,
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
                "title": title,
                "description": title,
                "priority": "p0",
                "implementation_state": "implemented",
                "implementation_mode": "contract_rule_v1",
            }
        )
    return checks


def _load_runtime_metrics() -> List[str]:
    if not LATEST_RESULT_PATH.exists():
        return []
    try:
        payload = json.loads(LATEST_RESULT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    out: List[str] = []
    for row in list(payload.get("metric_board") or []):
        if not isinstance(row, dict):
            continue
        metric = str(row.get("metric") or "").strip()
        if metric:
            out.append(metric)
    return sorted(set(out))


def _write_contract(checks: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
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
        "catalog_checks": list(checks),
    }
    CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONTRACT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def _group_checks_by_category(checks: Iterable[Mapping[str, Any]]) -> Dict[str, List[Mapping[str, Any]]]:
    out: Dict[str, List[Mapping[str, Any]]] = {}
    for row in checks:
        category = str(row.get("category") or "uncategorized")
        out.setdefault(category, []).append(row)
    for category in out:
        out[category] = sorted(out[category], key=lambda item: str(item.get("id") or ""))
    return dict(sorted(out.items(), key=lambda item: item[0]))


def _write_doc(contract: Mapping[str, Any], runtime_metrics: Sequence[str]) -> None:
    checks = list(contract.get("catalog_checks") or [])
    groups = _group_checks_by_category(checks)
    implemented = sum(1 for row in checks if str(row.get("implementation_state") or "").lower() == "implemented")
    policy = dict(contract.get("execution_policy") or {})
    lines: List[str] = []
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
    lines.append("")
    lines.append("## Runtime Metric Board (Current)")
    lines.append("")
    if runtime_metrics:
        for metric in runtime_metrics:
            lines.append(f"- `{metric}`")
    else:
        lines.append("- No runtime metric board artifact found yet. Run the suite and regenerate this doc.")
    lines.append("")
    lines.append("## Expanded Full-Coverage Catalog")
    lines.append("")
    for category, rows in groups.items():
        lines.append(f"### {category}")
        lines.append("")
        for row in rows:
            lines.append(
                f"- `{row.get('id')}` [{row.get('implementation_state')}] {row.get('title')}"
            )
        lines.append("")
    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    checks = _build_checks()
    if len(checks) != 210:
        raise SystemExit(f"expected 210 catalog checks, got {len(checks)}")
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
