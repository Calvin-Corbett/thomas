# Changelog

This public changelog starts with the first public release snapshot. Older private
working-branch notes are intentionally not included in the public repository.

## [Unreleased]

- Added public repo guidance docs: `docs/AGENT_START_HERE.md`, `docs/FEATURE_MATRIX.md`, `docs/REPO_MAP.md`, `docs/ARCHITECTURE_OVERVIEW.md`, and `docs/ROADMAP.md`.
- Added GitHub issue templates, PR template, release template, and Copilot/agent guidance for install failures, bugs, features, and structured agent tasks.
- Documented Infinite as the planned Phase 02 companion app and Thomas OS as a concept-stage Phase 03 direction.

## [0.14.60] - 2026-04-24

- Added `support.cmd` and `scripts/support_bundle.ps1` to collect redacted install/startup diagnostics in `runtime\support\`.
- Fixed Easy Setup completion so the verified model profile is persisted as the active profile and applied immediately.
- Added local networking/firewall guidance to setup diagnostics for `127.0.0.1:8899` troubleshooting.
- Hardened the Windows installer workflow with a silent install and first-run wizard smoke test.

## [0.14.59] - 2026-04-24

- Published the first public Thomas snapshot.
- Included the local Windows launcher path, setup and repair commands, server
  runtime, web UI, memory, tools, guardrails, model setup, and public GitHub
  release checks.
- Documented the local-first default networking posture and first-run install
  behavior.
