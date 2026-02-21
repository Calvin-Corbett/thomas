# Thomas Workboard

Last updated: 2026-02-20

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

## Current Priorities

1. Companion store compliance hardening
- Plan: `plans/thomas/companion/STORE_COMPLIANCE_PLAN.md`
- Status: in progress
- Next milestone: Phase 0 + Phase 1 implementation

2. Companion builder UX + runtime quality
- Plan: `plans/thomas/ui/UI_UPGRADE_PLAN.md`
- Status: backlog / partial
- Next milestone: validate scope against current UI architecture

3. Reliability and capability expansion
- Plan: `plans/thomas/roadmap/WEEKLY_DEEP_DIVE_PLAN.md`
- Status: mixed (contains implemented and pending tracks)
- Next milestone: refresh implementation status by track

4. Launch readiness
- Plan: `plans/thomas/launch/LAUNCH_V1_PLAN.md`
- Status: pending refresh
- Next milestone: align launch criteria with current repo reality

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
