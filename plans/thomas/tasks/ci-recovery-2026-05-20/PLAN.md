# Plan: CI gate recovery sprint

**Task ID:** ci-recovery-2026-05-20
**Owner:** claude
**Linked problem:** [PROBLEM.md](../../problems/ci-recovery-2026-05-20/PROBLEM.md)

## Goal

Clear every CI gate failure on dev so the repo is ready for more work without
carrying gate debt forward.

## Approach

Fix each failure in-session rather than deferring. Per Calvin's directive on
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
- [ ] Publish dev → public main (deliberate — requires Calvin to toggle branch protection).
- [ ] Release the claim.
