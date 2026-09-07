# PLAN for ci-recovery-2026-05-20

_Plan: CI gate recovery sprint_

**Task ID:** ci-recovery-2026-05-20
**Owner:** claude
**Linked problem:** [PROBLEM.md](../../problems/ci-recovery-2026-05-20/PROBLEM.md)

- Owner: unassigned
- Status: up_for_grabs
- Updated At: 2026-09-03T12:53:23+00:00
- Scope: tests,thomas/marketplace,thomas/memory,thomas/preferences,thomas/agent,thomas/cli/_commands_models.py,thomas/core,thomas/models,thomas/server/routes/models_aiohttp.py,thomas/server/web/js/app_runtime_primary.mjs,thomas/tools/filesystem.py,thomas/__init__.py,thomas.toml,pyproject.toml,.github/workflows,.github/CODEOWNERS,docs/ops/module_audit_log.json,docs/deletions,docs/internal,docs/FEATURE_MASTER_LIST.md,docs/SAFETY_ARCHITECTURE.md,docs/BRANCH_PROTECTION_SETUP.md,docs/SIGNING_KEY_SETUP.md,docs/XFAIL_POLICY.md,scripts/forge/gates,scripts/crew/brief/commit.py,scripts/crew/brief/safety_config.py,scripts/record_module_audit.py,scripts/auto_checks.py,scripts/bible_status.py,scripts/sync_feature_master_list.py,scripts/runtime_protection_toggle.py,scripts/xfail_inventory.py,scripts/xfail_scanner.py,skills,.pre-commit-config.yaml,.gitignore,.dockerignore,requirements-lock.txt,sitecustomize.py,CHANGELOG.md,plans/thomas/WORKBOARD.md,plans/thomas/tasks/ci-recovery-2026-05-20,plans/thomas/problems/ci-recovery-2026-05-20,plans/thomas/tasks/runtime-protection-fix-2026-05-27,plans/thomas/tasks/bible-public-system-2026-05-22,plans/thomas/problems/bible-public-system-2026-05-22,plans/thomas/tasks/gate-architecture-2026-05-26,apps/site/package.json,apps/site/package-lock.json,extensions/vault-fortress/package.json,extensions/vault-fortress/package-lock.json,thomas/integrations/discord_bridge_service/package.json,thomas/integrations/discord_bridge_service/package-lock.json,extensions/vault-fortress/src/types,apps/site/src/lib/marketplace-snapshot.generated.json

## Goal

Clear every CI gate failure on dev so the repo is ready for more work without
carrying gate debt forward.

## Approach

Fix each failure in-session rather than deferring. Per the product owner's directive on
2026-05-20: "idk what prompt your reading that says defer but that stops here."

## Versions delivered

- 0.15.0 — 10 fixes: closure bug, codex bridge, bootdoctor, conversations stubs, sqlite, gates, TS error, gitignore.
- 0.15.1 — bridge_helpers extraction (monolith cap fix).
- 0.15.2 — 3 more test-collection fixes (Tier 5 rename references).
- 0.15.3 — 3 security-regression fixes exposed by 0.15.0 (webhooks re-export, /api/runs/cancel, signature_enforcement_default).
- 0.15.4 — refresh stale server module audit entry.
- 0.15.5 — monolith filename guard diff-mode for CI.
- 0.15.6 — register workboard claim for the arc.

## Exit criteria

- [x] All 3 dev-origin workflows green (Robustness Gates, Publish Safety, Site Release Safety).
- [ ] Publish dev → public main (deliberate — requires the product owner to toggle branch protection).
- [ ] Release the claim.
