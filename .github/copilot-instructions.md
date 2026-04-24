# Thomas Agent Instructions

Start every task by reading `docs/AGENT_START_HERE.md` and
`docs/FEATURE_MATRIX.md`, then read `docs/AI_DEVELOPMENT_WORKFLOW.md`.
This repo is too large to infer product status from file existence alone.

Core rules:

- Keep the public default local-first and loopback-only.
- Do not add secrets, personal notes, local caches, support ZIPs, or private
  release history.
- Do not describe Partial, Prototype, or Planned features as finished.
- Do not bypass guardrails, approvals, release preflight, repo hygiene, or tests.
- Do not bypass the AI workflow contract or remove workflow enforcement.
- Prefer focused, testable changes and update docs when user-facing behavior
  changes.
- For install or GitHub release work, run the public safety checks before
  proposing publication.

Useful docs:

- `README.md`
- `DOCUMENTATION_INDEX.md`
- `docs/AGENT_START_HERE.md`
- `docs/AI_DEVELOPMENT_WORKFLOW.md`
- `docs/FEATURE_MATRIX.md`
- `docs/REPO_MAP.md`
- `docs/ARCHITECTURE_OVERVIEW.md`
- `docs/NETWORKING_AND_FIREWALL.md`
- `docs/ROADMAP.md`

Required release commands for install/GitHub/release changes:

- `python scripts/check_ai_workflow_contract.py`
- `python scripts/github_publish_preflight.py --json --strict --deep`
