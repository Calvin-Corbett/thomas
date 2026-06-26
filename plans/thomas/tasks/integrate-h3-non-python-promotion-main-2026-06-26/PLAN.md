# PLAN for integrate-h3-non-python-promotion-main-2026-06-26

- Owner: codex-merge-coordinator
- Status: in_progress
- Updated At: 2026-06-26T02:14:30+00:00
- Scope: thomas/forge/anvil/evolve.py,tests/test_cli_evolve_commands.py,CHANGELOG.md,docs/THREAT_MODEL_WEB_API.md,.github/workflows/gates.yml,.github/allowed_signers,plans/thomas/WORKBOARD.md,plans/thomas/tasks/integrate-h3-non-python-promotion-main-2026-06-26/PLAN.md,plans/thomas/problems/integrate-h3-non-python-promotion-main-2026-06-26/PROBLEM.md

## Summary

integrate-h3-non-python-promotion-main-2026-06-26

## Approach

- Preserve the focused evolve promotion implementation and tests.
- Refresh only the release-hygiene threat-model cadence metadata required by the protected main path.
- Add the GitHub SSH allowed-signers configuration needed for server-side signed-commit verification to recognize the existing signed commits.
- Keep the branch queued through a PR targeting `origin/main`; do not push directly to `origin/main`.
