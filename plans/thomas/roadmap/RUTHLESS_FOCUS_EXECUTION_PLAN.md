# Thomas Ruthless Focus Execution Plan (2026-02-22)

Status: in progress
Owner: core platform team
Canonical scope: beat competitors by over-executing on three product truths, not command-count parity.

## Why this plan exists

Thomas already has broad surface area. The bottleneck is not "missing one more command". The bottleneck is operator trust under real-world setup, failure, and scale conditions.

This plan de-scopes parity work and concentrates on three differentiators with hard outcomes.

## Ruthless De-Scope (Non-Goals)

The following are de-prioritized unless required by active enterprise deals:

1. Full connector parity across every chat platform in one cycle.
2. Native app breadth-first parity (Android/iOS/macOS all at once).
3. Tail-end CLI parity work that does not move activation, reliability, governance, or retention metrics.

## The Three Differentiators

## D1) Setup-to-Success Engine

Definition: Thomas gets users from install to reliable first value in minutes, then self-recovers when setup drifts.

Primary KPIs:
1. First-run completion rate >= 90%.
2. Median time-to-ready <= 8 minutes.
3. One-click recovery success rate >= 80% for top 10 setup failures.
4. Setup-related support ticket rate down >= 50%.

Scope:
1. Onboarding UX rewrite (guided setup, dependency approval clarity, progress persistence).
2. Recovery flow rewrite (`/api/setup/repair` + UI "repair now" playbooks).
3. Commercial support surfaces: troubleshooting matrix, config validation, migration guides.

## D2) Trust, Governance, and Safety Core

Definition: operators can safely run Thomas in teams with auditable controls, strict policy, and incident readiness.

Primary KPIs:
1. Zero open high-severity security issues on active surfaces.
2. 100% mutating HTTP routes with explicit authz + CSRF posture documented and tested.
3. Threat model refresh and abuse-case regression cadence sustained weekly.
4. Time-to-contain in incident drill <= 30 minutes.

Scope:
1. Security program cadence (threat modeling, dependency policy, incident drills).
2. Governance model (RBAC, approvals, audit, policy packs).
3. Release discipline (versioned contracts, deprecation guarantees, migration assurances).

## D3) Reliability Under Burst and Duration

Definition: Thomas behaves predictably across multi-day soak, burst load, and partial-failure conditions.

Primary KPIs:
1. 7-day soak pass with no critical service corruption.
2. P95 request latency and queue SLOs maintained under burst profile.
3. Failure-rate SLO met under failure injection scenarios.
4. Ecosystem compatibility pass-rate >= 95% on certified extension matrix.

Scope:
1. Real-world soak runs with fault injection.
2. Performance engineering (cold start, token/cost efficiency, queue behavior).
3. Ecosystem strategy (stable extension SDK contracts + compatibility test suite).
4. Outcome feedback loop (telemetry + user interviews + weekly reprioritization).

## Mapping from User Direction (1-10) to D1-D3

1. Ruthless de-scope -> D1/D2/D3 focus boundaries (this plan).
2. Onboarding + recovery UX rewrite -> D1.
3. Commercial docs/support surfaces -> D1.
4. Real-world soak testing -> D3.
5. Security maturity program -> D2.
6. Performance engineering -> D3.
7. Governance + collaboration model -> D2.
8. Release discipline -> D2.
9. Ecosystem strategy -> D3.
10. Telemetry + interviews + weekly outcomes loop -> D3 with D1/D2 input.

## 90-Day Delivery Slices

## Slice A (Weeks 1-3): Blockers and Instrumentation

Exit criteria:
1. Security blocker set closed and regression-tested.
2. Onboarding funnel telemetry complete (step-level, failure reason, recovery outcomes).
3. Config validator and support docs shipped.
4. Soak/perf harness baseline running in CI/nightly.

## Slice B (Weeks 4-8): Productized Reliability and Governance

Exit criteria:
1. Onboarding/recovery UX shipped with recovery presets.
2. Governance model v1 shipped (roles, approvals, audit baseline).
3. Threat model + abuse-case suite enforced in release flow.
4. Burst/perf budgets enforced and visible on dashboards.

## Slice C (Weeks 9-12): Hardening and Proof

Exit criteria:
1. 7-day soak passes consistently.
2. Incident drills and rollback rehearsals pass.
3. Extension compatibility suite active for certified SDK versions.
4. Outcome loop demonstrates measurable KPI movement vs Slice A baseline.

## Weekly Operating Cadence

1. Monday: KPI delta review (activation, recovery, reliability, security posture).
2. Tuesday-Thursday: focused build/test work against D1-D3 milestones.
3. Friday: soak/perf/security review + decision log + next-week reprioritization.

## Must-Pass Gates before milestone close

1. Security regression suite green.
2. Onboarding and recovery flow e2e tests green.
3. Soak/perf budget checks green for current slice thresholds.
4. Migration and deprecation contract checks green.
5. Changelog and release notes reflect any behavior changes.

## Decision Rule

If work does not materially improve D1, D2, or D3 KPIs in the current slice, it is de-scoped.
