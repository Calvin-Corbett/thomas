# Thomas Workboard

Last updated: 2026-02-22

This file is the active execution board for agents.

## Recent Completed

1. Planning structure normalization
- Added canonical `plans/` hierarchy and Thomas workboard.
- Added legacy pointer files for moved plan docs.
- Added repo-structure protocol and agent startup references.
- Added enforceable gates: `check_plan_structure_gate.py` and `check_release_update_gate.py`.

2. Companion compliance control-plane foundation (Phase 0/1)
- Added versioned policy profiles: `thomas/companion/policy_profiles/*.json`.
- Added policy engine and report store: `thomas/companion/policy/`.
- Added compliance endpoints:
  - `GET /api/companion/v1/policy/profiles`
  - `GET /api/companion/v1/policy/profile/{profile_id}`
  - `POST /api/companion/v1/compliance/check`
- Gated `ship` and `releases/publish` with compliance checks.
- Extended device/release schemas with policy/compliance metadata.
- Added builder UI compliance panel + fields in `/companion`.
- Added tests for policy validation and server compliance flows.
- Added release handoff doc: `docs/COMPANION_BUILDER_RELEASE_GUIDE.md`.

3. Workbench operator-mode baseline contract
- Added `docs/WORKBENCH_OPERATOR_PROTOCOL.md` as the canonical contract for AI-first tab semantics.
- Updated `AGENTS.md` startup guidance to load the operator protocol and enforce operator-surface alignment.
- Added a global `Operator Mode` preamble in workbench runtime (`thomas/server/web/js/app.js`) so tabs default to dispatch/monitor/review semantics where Thomas executes work.

3. Onboarding rollout gate hardening (Slice A milestone support)
- Added strict warning policy option to `scripts/check_onboarding_outcomes_gate.py` with low-sample warning ignore support.
- Upgraded robustness and nightly workflows to run onboarding outcomes gate in strict mode with low-sample tolerance.
- Added script-level regression tests and CI workflow guard assertions for gate command enforcement.

## Current Priorities

1. Ruthless focus execution
- Plan: `plans/thomas/roadmap/RUTHLESS_FOCUS_EXECUTION_PLAN.md`
- Status: in progress
- Next milestone: Slice A blocker closure + instrumentation gates

2. Companion store compliance hardening
- Plan: `plans/thomas/companion/STORE_COMPLIANCE_PLAN.md`
- Status: in progress
- Next milestone: Phase 0 + Phase 1 implementation

3. Companion builder UX + runtime quality
- Plan: `plans/thomas/ui/UI_UPGRADE_PLAN.md`
- Status: backlog / partial
- Next milestone: validate scope against current UI architecture

4. Reliability and capability expansion
- Plan: `plans/thomas/roadmap/WEEKLY_DEEP_DIVE_PLAN.md`
- Status: mixed (contains implemented and pending tracks)
- Next milestone: refresh implementation status by track

5. Launch readiness
- Plan: `plans/thomas/launch/LAUNCH_V1_PLAN.md`
- Status: pending refresh
- Next milestone: align launch criteria with current repo reality

6. Onboarding UX + recovery
- Plan: `plans/thomas/onboarding/THOMAS_ONBOARDING_UX_PLAN.md`
- Status: in progress
- Next milestone: convert setup/repair telemetry and support surfaces into enforced rollout gates

7. Virtual office roadmap execution
- Plan: `plans/thomas/ui/VIRTUAL_OFFICE_MASTER_BACKLOG.md`
- Status: backlog
- Next milestone: lock acceptance criteria for onboarding and soak slices in office simulation

8. UI interiors redesign
- Plan: `plans/thomas/ui/TAB_INTERIORS_REDESIGN_PLAN.md`
- Status: backlog
- Next milestone: align redesign milestones with the primary UI upgrade plan

9. Asset Studio external tool integration
- Plan: `plans/thomas/ui/ASSET_STUDIO_INTEGRATION_PLAN.md`
- Status: active proposal
- Next milestone: ship Phase 0 connector runtime + API skeleton

## Supporting Docs (Not Plan Sources)

- `docs/COMPANION_PLATFORM_SCOPE.md`
- `docs/COMPANION_APP_INTEGRATION.md`
- `docs/PROJECT_SCOPE.md`
- `docs/RULES_OF_THE_ROAD_PROTOCOL.md`

## Repo Organization Rules For Agents

- New execution plans go in `plans/` only.
- Keep one product folder per domain (for example `plans/thomas/`).
- If moving a plan from `docs/` or repo root, leave a pointer file.
- Do not treat `tasks/` note files as active project plans.

## Legacy Plan Redirects

- `PLAN-UI-UPGRADE.md` -> `plans/thomas/ui/UI_UPGRADE_PLAN.md`
- `docs/WEEKLY_DEEP_DIVE_PLAN.md` -> `plans/thomas/roadmap/WEEKLY_DEEP_DIVE_PLAN.md`
- `docs/LAUNCH_V1.md` -> `plans/thomas/launch/LAUNCH_V1_PLAN.md`
- `docs/COMPANION_STORE_COMPLIANCE_PLAN.md` -> `plans/thomas/companion/STORE_COMPLIANCE_PLAN.md`
- `docs/THOMAS_ONBOARDING_UX_PLAN.md` -> `plans/thomas/onboarding/THOMAS_ONBOARDING_UX_PLAN.md`

