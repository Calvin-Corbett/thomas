# Agent Start Here

This repo is large. Do not try to understand it by scanning every file first.
Use this path to get useful context quickly without inventing product claims.

## First Five Files

Read these in order:

1. `README.md` - user install path, product promise, and public-release stance.
2. `docs/FEATURE_MATRIX.md` - feature status, audience, entry points, and tests.
3. `docs/AI_CONTRIBUTOR_GUARDRAILS.md` - public-safe AI and contributor rules.
4. `docs/FUNCTIONALITY_INVENTORY.md` - capability inventory and readiness notes.
5. `docs/REPO_MAP.md` - top-level directory map.
6. `docs/ARCHITECTURE_OVERVIEW.md` - install/runtime/companion diagrams.

Use `DOCUMENTATION_INDEX.md` after that when you need an area-specific doc.

## Product In One Paragraph

Thomas is a local-first AI workspace that starts as a Windows-installed browser
chat app and grows into guarded tools, memory, automation, Mission Control,
plugins, and companion-device workflows. The public default is private and
loopback-only. Remote access, integrations, and advanced builder paths are opt-in
and must keep authentication, policy, and audit boundaries intact.

## Do Not Miss These Capabilities

- Easy Setup and model/provider validation.
- Local support bundle and repair path.
- Guarded tool execution with approvals.
- Memory and retrieval.
- Mission Control jobs, objectives, approvals, and live activity.
- Evolve mode for guarded self-improvement sessions.
- Browser automation and visible browser smoke paths.
- Companion platform scaffolding and the planned Infinite app direction.
- Public release safety gates and GitHub Actions.
- Public AI contributor guardrails and GitHub Actions checks.

## Status Discipline

Follow the status labels in `docs/FEATURE_MATRIX.md`.

- Stable and Beta areas can be described as real public capabilities.
- Partial areas need careful caveats and should not be sold as turnkey.
- Prototype areas should be treated as scaffolding.
- Planned areas belong in roadmap language only.
- Internal areas are contributor or maintainer infrastructure.

Do not assume every module is production-ready. If code exists but the matrix
says Partial, do not upgrade the claim unless tests, docs, and user flow justify
it.

## Safe Work Rules

- Keep the default server bound to `127.0.0.1` unless a task is explicitly about
  remote deployment.
- Do not add secrets, personal notes, local caches, generated support bundles, or
  non-public release history.
- Do not add non-public website deployment instructions to the public branch.
- Do not bypass guardrails, approval checks, release preflight, or repo hygiene
  checks to make a change pass.
- Do not bypass the public AI guardrail contract in
  `docs/AI_CONTRIBUTOR_GUARDRAILS.md`.
- Prefer small, testable changes with clear public docs.
- When touching installer, setup, networking, or GitHub release behavior, run the
  public safety gates before publishing.

## Useful Commands

Run these from the repo root:

```powershell
python -m pytest tests\test_public_release_surface.py tests\test_product_surface_copy.py tests\test_public_repo_guidance.py -q
python scripts\check_ai_workflow_contract.py
python scripts\github_publish_preflight.py --json --strict --deep
python scripts\check_repo_hygiene.py --require-clean-worktree --strict --json
```

For installer/support work, also run the focused installer and support tests:

```powershell
python -m pytest tests\test_windows_installer_assets.py tests\test_support_bundle_script.py -q
```

## Where To Go Next

- Install or support issue: `docs/WINDOWS_INSTALLER_GUIDE.md`,
  `docs/NETWORKING_AND_FIREWALL.md`, and `support.cmd`.
- Chat behavior: `docs/CHAT_EXECUTION_MODEL.md` and `thomas/chat/README.md`.
- Web UI: `thomas/server/web/README.md`.
- API route work: `thomas/server/routes/README.md`.
- Tools: `thomas/tools/README.md`.
- Memory: `thomas/memory/README.md`.
- Companion/Infinite: `docs/THOMAS_INFINITE.md`,
  `docs/COMPANION_APP_INTEGRATION.md`, and `docs/COMPANION_PLATFORM_SCOPE.md`.
