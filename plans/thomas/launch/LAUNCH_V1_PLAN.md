# Thomas V1 Launch Readiness Plan

Last updated: 2026-02-25
Status: in progress (refreshed from pending)
Owner: Thomas core platform team

## 1) Launch Objective

Ship a V1 that is launchable for public/business use with:

1. Measurable reliability, safety, and governance.
2. Reproducible benchmark evidence against the pinned OpenClaw baseline.
3. A clear operator experience (setup -> execute -> recover) without requiring deep manual intervention.
4. A launch narrative and demo assets produced by Thomas after core gates are green.

This plan is functional-first. Visual polish and broad feature expansion remain secondary to launch gates.

## 2) Canonical Inputs

This plan is constrained by:

1. `docs/PROJECT_SCOPE.md` (hard competitive and release gates).
2. `plans/thomas/roadmap/RUTHLESS_FOCUS_EXECUTION_PLAN.md` (D1/D2/D3 KPI program).
3. `plans/thomas/onboarding/THOMAS_ONBOARDING_UX_PLAN.md` (setup/recovery funnel).
4. `docs/AGENT_COMPARISON_SUITE.md` (benchmark evidence method).
5. `plans/thomas/WORKBOARD.md` (active tasks and blockers).

## 3) V1 Must-Pass Launch Gates

### 3.1 Competitive Hard Win Gates (Required)

All must pass against pinned OpenClaw baseline on parity environment:

1. Task Success Rate: Thomas >= OpenClaw +10 percentage points.
2. p95 Time-to-First-Useful-Output: Thomas at least 20% faster.
3. Crash-Free Run Rate: Thomas >= 99.5%.
4. Autonomous Recovery Success: Thomas >= 95% within <=30s.
5. Unsafe Action Block Rate: Thomas >= 99%.
6. False Block Rate: Thomas <= 5%.
7. Cross-Provider Pass Rate: same corpus passes on >=3 provider profiles.
8. Cost-per-Success: no worse than OpenClaw by more than 5%.

Durability requirement:

1. Gates must remain green for 2 consecutive weekly benchmark runs before any "better than OpenClaw" claim.

### 3.2 D1/D2/D3 Product Gates (Required)

From ruthless-focus program, launch requires:

1. D1 Setup-to-Success:
   - first-run completion >= 90%
   - median time-to-ready <= 8 minutes
   - one-click recovery success >= 80% for top setup failures
2. D2 Trust/Governance/Safety:
   - zero open high-severity security issues on active surfaces
   - mutating route authz posture documented and tested
3. D3 Reliability Under Burst/Duration:
   - 7-day soak pass without critical corruption
   - burst/perf budget checks green for release slice

### 3.3 Release Discipline Gates (Required)

1. `python scripts/auto_checks.py --quick` passes.
2. `python scripts/auto_checks.py` passes (full gate run).
3. `python scripts/check_competitive_scope_gate.py` passes.
4. `python scripts/check_openclaw_metric_parity_gate.py` passes.
5. `python scripts/check_model_onboarding_gate.py` passes.
6. `python scripts/check_surface_parity.py` passes.
7. `python scripts/check_plan_structure_gate.py` passes.
8. `python scripts/check_release_update_gate.py` passes.

## 4) Required Evidence Bundle (No Evidence = No Launch)

| Evidence | Required file(s) | Refresh cadence |
|---|---|---|
| OpenClaw head-to-head benchmark JSON | `docs/openclaw_gap_runs/latest_full_suite_compare.json` | Weekly minimum |
| OpenClaw head-to-head benchmark markdown | `docs/openclaw_gap_runs/latest_full_suite_compare.md` | Weekly minimum |
| Pinned OpenClaw baseline metadata | `demo/baselines/openclaw.current.json` | When baseline changes |
| Agent comparison suite config | `demo/baselines/agent_comparison_suite.current.json` | With scoring/policy changes |
| Workboard state for launch blockers | `plans/thomas/WORKBOARD.md` | Continuous |
| Changelog + version readiness | `CHANGELOG.md`, `pyproject.toml`, `thomas/__init__.py` | Every behavior change |

Required benchmark command for comparable evidence:

```bash
python scripts/run_agent_comparison_suite.py --suite-config demo/baselines/agent_comparison_suite.current.json --focus-agent thomas --write --write-md
```

## 5) Current Reality Snapshot (2026-02-25)

1. Launch readiness is a top-10 program priority and was marked "pending refresh" before this update.
2. Multiple gap-closure streams are active on workboard (latency p95, competitor freshness, test density, large-file maintainability).
3. Additional OpenClaw/CrewAI gap tasks remain in `## Up For Grabs`; launch cannot close while key competitive gaps remain unowned.
4. Setup/recovery and governance programs are active in parallel plans but still require hard gate closure.
5. Launch readiness should be treated as a release-governance track, not a single feature.

## 6) Phased Execution Plan

## Phase L0: Contract Refresh and Ownership Lock (Current)

Exit criteria:

1. This launch plan reflects current hard gates and evidence policy.
2. All launch-critical workboard tasks are either active or explicitly blocked with owner and next action.
3. Benchmark and policy scripts are validated as runnable in the current repo.

## Phase L1: Gate Closure (Reliability + Governance)

Exit criteria:

1. D1 setup/recovery KPI instrumentation is producing stable weekly reports.
2. D2 security/governance checks are green with documented incident path.
3. D3 burst/soak checks pass for release thresholds.
4. Release discipline gates pass in CI and local verification.

## Phase L2: Competitive Proof Stability

Exit criteria:

1. All competitive hard win gates pass against pinned OpenClaw baseline.
2. The pass state holds for two consecutive weekly runs.
3. Remaining competitor pressure items are either closed or explicitly de-scoped with rationale.

## Phase L3: Launch Packaging and Go/No-Go

Exit criteria:

1. Launch notes capture exact baseline revision and evidence links.
2. Operator runbook for install/setup/recovery is complete and validated.
3. Launch demo package is complete and aligned with shipped capabilities.
4. Formal go/no-go review signs off with all required gates green.

## 7) Launch Demo Asset Requirements (Post-Gate, Pre-Launch)

Demo production is required, but only after L1/L2 gate closure.

Minimum deliverables:

1. Thomas-generated script + shot list.
2. Thomas-generated or Thomas-orchestrated visual/audio assets.
3. Voiceover and final edit export (`.mp4` + web-friendly variant).
4. Demonstrations of:
   - setup to first successful task
   - agent coordination (single + swarm)
   - memory continuity across sessions
   - recovery from a controlled failure case

Explicitly de-scoped from V1 unless separately approved:

1. Broad UI redesign.
2. New breadth-first platform integrations that do not move launch gates.
3. Feature demonstrations not backed by shipping/runtime evidence.

## 8) Immediate Next Actions (Next 7 Days)

1. Reconcile open launch-critical `Up For Grabs` tasks into owned work streams.
2. Run and publish fresh benchmark evidence using pinned suite config.
3. Produce a single launch gate scoreboard summary in `docs/openclaw_gap_runs/`.
4. Verify D1/D2/D3 KPI evidence paths and owners in weekly cadence.
5. Run full release discipline gates and log failures as launch blockers.

## 9) Decision Rule

V1 is launch-ready only when every required gate in Sections 3 and 4 is satisfied.
If any required gate is red, decision is `NO-GO`.
