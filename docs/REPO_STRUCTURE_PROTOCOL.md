# Repo Structure Protocol

Last updated: 2026-03-01

This document defines how Thomas is organized so any agent can enter the repo and execute work without guessing.

## 1) Top-Level Intent

- `thomas/`: product runtime and server code.
- `apps/`: optional platform clients and companion app scaffolds, when present.
- `tests/`: automated test coverage for product behavior.
- `docs/`: stable specs/protocols/reference docs (not active execution plans).
- `plans/thomas/`: active execution plans, workboards, and planning artifacts.
- Local intake/archive folders are ignored by Git and are not public source of truth.

## 2) Canonical Planning Layout

All active plans must live in `plans/thomas/`.

Current convention:
- `plans/README.md`: global planning rules.
- `plans/thomas/README.md`: Thomas plan hub and plan index.
- `plans/thomas/WORKBOARD.md`: active priorities + statuses.
- `plans/thomas/tasks/.../PLAN.md`: active task plans.
- `plans/thomas/problems/.../PROBLEM.md`: problem statements tied to task plans.
- domain plan files under `plans/thomas/<domain>/...`.

Do not create new random plan files at repo root or in `docs/`.
If a plan is moved, keep a pointer file at the old path.

## 3) Agent Startup Checklist

For every new task:
1. Run `python scripts/agent_startup_router.py --summary "<task summary>" [--path <repo/path>]...`
2. Read the returned lane card in `docs/ai/CHECKLISTS/`
3. Check `plans/thomas/WORKBOARD.md` for awareness of active claims and blockers
4. Load only the plans and reference docs that the lane points to

If there is conflict:
- `AGENTS.md` process rules win.
- Lane cards define the default startup path.
- Plan files define current execution intent.
- Docs define stable contracts.

## 4) Directory Rules

### 4.1 Code
- Put runtime/service code in `thomas/` only.
- Avoid duplicate implementations in ad-hoc folders.

### 4.2 Tests
- Every behavioral code change gets tests in `tests/`.
- Keep test file naming aligned to module scope.

### 4.3 Docs
- `docs/` is for stable reference docs:
  - protocols
  - API contracts
  - scope definitions
  - operational runbooks
- `docs/` should not be used as an active sprint board.

### 4.4 Plans
- Active execution plans live in `plans/thomas/` only.
- `plans/thomas/WORKBOARD.md` is the active board for agent coordination.
- `plans/thomas/README.md` must reference every non-generated plan file.

### 4.5 Intake/Archive
- Local intake/archive folders are ignored by Git and should not be linked as public source.
- Do not treat intake files as production source of truth until integrated into tracked code and docs.

## 5) Change Hygiene Requirements

## 5.1 Version + Changelog discipline
When a behavioral or user-visible change is shipped:
- bump version in:
  - `pyproject.toml`
  - `thomas/__init__.py`
- add changelog entry in `CHANGELOG.md`.
- run `python scripts/check_release_hygiene.py` before closing work.
- run `python scripts/check_release_update_gate.py` to enforce diff-aware update policy.

## 5.2 Plan update discipline
When a plan-driven milestone changes:
- update the corresponding plan status.
- update `plans/thomas/WORKBOARD.md` summary.

## 5.3 Pointer maintenance
If a file moved:
- leave old file as a short pointer to the canonical path.

## 6) Repo Health Audit Questions

Before closing work, agents should confirm:
1. Is the active plan in `plans/thomas/`?
2. Is workboard status updated?
3. Are version/changelog rules satisfied for shipped behavior changes?
4. Are tests present for behavior changes?
5. Are docs/spec updates in the right folder (`docs/` vs `plans/`)?
6. Did `python scripts/check_plan_structure_gate.py` pass?

## 7) Current Canonical Plan Paths (Thomas)

- `plans/thomas/companion/STORE_COMPLIANCE_PLAN.md`
- `plans/thomas/ui/UI_UPGRADE_PLAN.md`
- `plans/thomas/roadmap/WEEKLY_DEEP_DIVE_PLAN.md`
- `plans/thomas/launch/LAUNCH_V1_PLAN.md`
- `plans/thomas/onboarding/THOMAS_ONBOARDING_UX_PLAN.md`

## 8) Legacy Redirects (Expected)

These may exist as pointers and are intentional:
- `PLAN-UI-UPGRADE.md`
- `docs/WEEKLY_DEEP_DIVE_PLAN.md`
- `docs/LAUNCH_V1.md`
- `docs/COMPANION_STORE_COMPLIANCE_PLAN.md`
- `docs/THOMAS_ONBOARDING_UX_PLAN.md`

## 9) Automation Gates

- `python scripts/check_plan_structure_gate.py`
  - fails if active plan files drift outside `plans/`
  - fails if pointer redirects are missing/broken
  - fails if workboard/plan hub references are stale

- `python scripts/check_release_update_gate.py`
  - diff-aware enforcement for version/changelog updates on product-surface changes

- `python scripts/check_release_hygiene.py`
  - validates version consistency (`pyproject.toml` vs `thomas/__init__.py`)
  - validates changelog section presence

- `.pre-commit-config.yaml`
  - mirrors structure/release gates for local commit-time enforcement
  - includes repo hygiene clean-worktree enforcement at pre-push time
  - install with:
    - `pre-commit install`
    - `pre-commit install --hook-type pre-push`
