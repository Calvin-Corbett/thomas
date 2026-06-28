# Project Scope: Thomas

Thomas is an autonomous AI execution platform for public use, not a localhost-only assistant.

## Consumer Mission (Permanent)

Thomas exists to deliver consumer value first: reliable execution, strong safety, fast response,
predictable cost, and clear operator control.
Outperforming Reference CLI is a quality instrument to improve those outcomes, not the sole product purpose.

## Competitive Program (Release-Bound)

For release planning, Thomas must be measurably better than the currently released Reference CLI baseline
on capability surface and execution outcomes.
Scope for this program is not considered complete unless the win gates below are met.

## Reference CLI Baseline Lock

- Baseline system: Reference CLI.
- Pinned baseline artifact: `demo/baselines/reference_cli.current.json`.
- Current pinned Reference CLI baseline commit: `fa6c0e1b` (captured 2026-03-06 from `origin/main`).
- Baseline revision policy: the exact Reference CLI commit/tag used for head-to-head runs must be recorded in release notes and benchmark artifacts.
- Baseline environment parity: same hardware tier, same provider tier, same task corpus, same timeout budgets.
- Baseline refresh cadence: monthly or when Reference CLI releases a major capability update.

## Capability Contract (Must Exist)

Thomas must deliver all of the following:

- Hybrid deployment:
  - local mode (single-user, local hardware, local models)
  - remote mode (public/business-hosted server, authenticated and rate-limited)
- Hybrid model orchestration:
  - local model providers + cloud/API model providers
  - policy/capability routing across profiles
  - shared tool/event semantics across providers
- Execution-first autonomy:
  - objective/step state machine with persistence
  - approvals, audit chain, retries, recovery/reconciliation
  - long-horizon execution modes (including batch/scheduled paths)
  - operator-visible mission control workspace for live agent state, movement, and intervention controls
- Workflow intelligence:
  - chain, parallel, routing, evaluator-optimizer strategies
  - capability-aware fallback for profile/capability mismatch
- Extensibility:
  - stable connector/tool protocol for external integrations
  - strict onboarding gates for new model providers/capabilities
- Workbench operator-mode baseline:
  - studio/workbench tabs are AI-first control surfaces where Thomas executes jobs
  - tabs prioritize dispatch, monitoring, and output review over manual full-editor replication
  - user-created tabs inherit operator-mode semantics by default

## Hard Win Gates (Must All Pass)

Against the pinned currently released Reference CLI baseline on the same benchmark suite:

- Task Success Rate: Thomas must be at least `+10` percentage points.
- p95 Time-to-First-Useful-Output: Thomas must be at least `20%` faster.
- Crash-Free Run Rate: Thomas must be at least `99.5%`.
- Autonomous Recovery Success (provider/tool failures): Thomas must be at least `95%` within `<=30s`.
- Unsafe Action Block Rate: Thomas must be at least `99%`.
- False Block Rate (safe action blocked): Thomas must be `<=5%`.
- Cross-Provider Pass Rate: same task corpus must pass on at least `3` distinct provider profiles.
- Cost-per-Success: median token+tool cost per successful task must be no worse than Reference CLI by more than `5%`.

## Evidence Policy

- No subjective release claims without benchmark evidence.
- Reference CLI outperformance is necessary for this release program, but not sufficient on its own; consumer reliability/safety/cost gates are required.
- "Better than Reference CLI" may be stated only when every hard win gate is green.
- Gate status must remain green for two consecutive weekly benchmark runs before claiming durable superiority.

## Non-Goals

- Regressing to localhost-only assumptions.
- Provider-specific behavior that breaks shared tool/event contracts.
- Shipping model onboarding changes without validation evidence.
- Claiming "better than Reference CLI" using ad-hoc demos without reproducible benchmark artifacts.

## Enforcement

- Historical competitive-scope and Reference CLI parity launch checks from February 2026 are retired; do not route current enforcement to deleted launch-gate scripts.
- Docs reliability runner: `scripts/doc.py`
- Model onboarding gate: `scripts/forge/gates/model_onboarding_gate.py`
- Feature catalog gate: `scripts/forge/gates/feature_catalog_gate.py`
- API capability onboarding protocol: `docs/API_CAPABILITY_ONBOARDING_PROTOCOL.md`
- Surface parity gate: `scripts/forge/gates/surface_parity.py`
- Robustness CI workflow: `.github/workflows/robustness-gates.yml`
