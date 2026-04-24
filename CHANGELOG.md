# Changelog

This public changelog starts with the first public release snapshot. Older private
working-branch notes are intentionally not included in the public repository.

## [Unreleased]

- No unreleased changes.

## [0.14.62] - 2026-04-24

- Added a public install landing page that directs normal users to the Windows
  release installer instead of the source ZIP.
- Added optional trusted Windows installer code-signing support to the GitHub
  release workflow. Signing is skipped unless maintainer certificate secrets are
  configured.
- Added first-run failure guidance that points users to `repair.cmd`,
  `bootdoctor.cmd`, `support.cmd`, the support ZIP folder, and the GitHub
  install-failure issue form.
- Opted public GitHub Actions workflows into GitHub's Node 24 JavaScript action
  runtime compatibility path.

## [0.14.61] - 2026-04-24

- Added public repo guidance docs: `docs/AGENT_START_HERE.md`, `docs/FEATURE_MATRIX.md`, `docs/REPO_MAP.md`, `docs/ARCHITECTURE_OVERVIEW.md`, and `docs/ROADMAP.md`.
- Added GitHub issue templates, PR template, release template, and Copilot/agent guidance for install failures, bugs, features, and structured agent tasks.
- Documented Infinite as the planned Phase 02 companion app and Thomas OS as a concept-stage Phase 03 direction.
- Removed stale private/internal repo guidance, website-only helpers, and personal example text from the public snapshot.
- Hid maintainer-only release commands from normal CLI help and gated release publishing behind an explicit maintainer environment flag.
- Enabled runtime guardrails by default for fresh public profiles so `/api/health` boots cleanly instead of degraded.
- Cleaned public install/source guidance, feature-list output, and stale intake-folder wording so the GitHub surface is easier for users and agents to read.

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
