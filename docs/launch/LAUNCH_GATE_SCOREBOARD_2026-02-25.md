# Launch Gate Scoreboard

Last updated: 2026-02-25
Scope: Thomas V1 launch-readiness gate snapshot

## Evidence Inputs

1. Fresh comparison run artifact:
   - `output/launch/full_suite_compare_2026-02-25.json`
   - `output/launch/full_suite_compare_2026-02-25.md`
   - `computed_at_utc`: `2026-02-25T16:31:07Z`
2. Gate command results:
   - `python scripts/check_competitive_scope_gate.py` -> PASS
   - `python scripts/check_reference_cli_metric_parity_gate.py` -> FAIL
   - `python scripts/check_model_onboarding_gate.py` -> FAIL
   - `python scripts/check_surface_parity.py` -> FAIL
   - `python scripts/check_release_update_gate.py` -> PASS
   - `python scripts/check_plan_structure_gate.py` -> PASS
   - `python scripts/auto_checks.py --quick` -> FAIL

## Overall Verdict

`NO-GO` for V1 launch right now.

Primary blockers:

1. Hard launch gates are incomplete (`UNKNOWN`/`BLOCKED`) for safety/cross-provider/cost evidence.
2. Competitive gate `p95` speed target is not met on current benchmark proxy.
3. Release discipline gates are not fully green.

## Competitive Hard Win Gates

| Gate | Target | Current Evidence | Status |
|---|---|---|---|
| Task Success Rate | >= Reference CLI +10pp | `benchmark.success_rate_mean`: Thomas `0.4` vs Reference CLI `0.2` (`+20pp`) | PASS (single-run) |
| p95 Time-to-First-Useful-Output | >=20% faster than Reference CLI | Proxy `benchmark.raw_elapsed_seconds_p95`: Thomas `21.125` vs Reference CLI `21.06285` (`-0.295%`) | FAIL |
| Crash-Free Run Rate | >=99.5% | Proxy `resilience.probes.pass_rate`: Thomas `1.0` (`5/5` runs) | PASS (proxy-only) |
| Autonomous Recovery Success <=30s | >=95% | No direct metric in current artifact | UNKNOWN |
| Unsafe Action Block Rate | >=99% | No direct metric in current artifact | UNKNOWN |
| False Block Rate | <=5% | No direct metric in current artifact | UNKNOWN |
| Cross-Provider Pass Rate | >=3 provider profiles | No explicit cross-provider pass metric in current artifact | UNKNOWN |
| Cost-per-Success | <=5% worse than Reference CLI | Token efficiency telemetry coverage: Thomas `0.0`, Reference CLI `0.0`; score is `n/a` | BLOCKED (missing telemetry) |

Durability gate:

1. Requirement: 2 consecutive weekly green runs.
2. Current: not satisfied from this single snapshot.

## Benchmark Program Snapshot

1. Thomas ranking:
   - `head_to_head_score`: `93.671`
   - `overall_suite_score`: `97.626`
   - `overall_benchmark_capability_score`: `74.117`
   - `governance_verdict`: `NO_GO`
2. Open gaps for Thomas (`open_gap_count=8`) include:
   - `benchmark.raw_elapsed_seconds_p95`
   - `benchmark.weighted_score_stddev`
   - `benchmark.raw_elapsed_seconds_stddev`
   - `benchmark.success_rate_stddev`
   - `tests.to_code_file_ratio`
   - `code.non_python_files`
   - `maintainability.large_code_files_over_800`

## Release Discipline Gates

| Gate | Result | Notes |
|---|---|---|
| `check_competitive_scope_gate.py` | PASS | Scope contract and baseline commit (`d17a1f3`) present |
| `check_reference_cli_metric_parity_gate.py` | FAIL | `cli.depth.update`: Thomas `0` vs Reference CLI `2` |
| `check_model_onboarding_gate.py` | FAIL | Missing `docs/MODEL_ONBOARDING_LOG.md` for model-surface changes |
| `check_surface_parity.py` | FAIL | Missing `thomas/server/web/js/chat.js` expected by gate |
| `check_release_update_gate.py` | PASS | Version/changelog and surface checks passed |
| `check_plan_structure_gate.py` | PASS | Plan locations and pointers valid |
| `auto_checks.py --quick` | FAIL | Ruff fatal lint (`F821`) with 44 errors |

## D1/D2/D3 Status (Ruthless Focus Program)

| Area | Launch Target | Current Status |
|---|---|---|
| D1 Setup-to-Success | completion >=90%, median ready <=8m, repair >=80% | UNKNOWN (not measured in this run) |
| D2 Trust/Governance/Safety | zero open high-sev + authz/CSRF coverage | PARTIAL (security probes pass-rate high, but hard safety gates not proven) |
| D3 Reliability Under Burst/Duration | 7-day soak + burst SLOs | PARTIAL (benchmark/resilience probes present; 7-day soak evidence not shown here) |

## Immediate Launch-Blocker Actions

1. Close `p95` latency and variance gaps versus Reference CLI (`benchmark.raw_elapsed_seconds_p95`, stability stddev metrics).
2. Add token telemetry capture so cost-per-success gates are measurable.
3. Resolve parity gate failure for `cli.depth.update`.
4. Resolve model onboarding gate (`docs/MODEL_ONBOARDING_LOG.md` + related model-surface workflow).
5. Fix `check_surface_parity.py` expectation mismatch (`chat.js`) or update gate to current frontend architecture.
6. Clear fatal lint baseline (`auto_checks.py --quick` currently blocked by 44 `F821` issues).
