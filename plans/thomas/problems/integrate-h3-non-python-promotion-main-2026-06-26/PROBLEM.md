# PROBLEM for integrate-h3-non-python-promotion-main-2026-06-26

task_id: `integrate-h3-non-python-promotion-main-2026-06-26`

- Owner: codex-merge-coordinator
- Status: in_progress
- Updated At: 2026-06-26T02:14:30+00:00
- Scope: thomas/forge/anvil/evolve.py,tests/test_cli_evolve_commands.py,CHANGELOG.md,docs/THREAT_MODEL_WEB_API.md,.github/workflows/gates.yml,.github/allowed_signers,plans/thomas/WORKBOARD.md,plans/thomas/tasks/integrate-h3-non-python-promotion-main-2026-06-26/PLAN.md,plans/thomas/problems/integrate-h3-non-python-promotion-main-2026-06-26/PROBLEM.md

## Current Problem

Prepare the H3 non-Python evolve promotion hardening lane for the protected `origin/main` merge path.

## Blocking Details

- Initial local implementation and focused verification were green.
- PR #60 exposed two server-side gate issues during main-target queuing: the ignored problem record was not tracked, and the signed-commits workflow needed the repository SSH allowed-signers file configured before `%G?` verification.
- The Web/API threat-model cadence review was refreshed because release hygiene blocked the first PR branch push.
