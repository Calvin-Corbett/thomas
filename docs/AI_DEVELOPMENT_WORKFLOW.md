# AI Development Workflow

This file is mandatory operating policy for AI agents working on Thomas. It is
not advice. If the workflow is wrong, change this file and the contract test in
the same PR so CI proves the new rule is intentional.

## Operating Model

- The private repo is the source of development truth.
- The public repo is a sanitized release artifact plus public-facing fixes.
- AI agents work through issues, task records, or clearly scoped PRs.
- One issue or task should map to one branch or one scoped commit.
- `main` is the only public branch that should matter to users.
- Public release changes must be promoted through checks, not copied by memory.

## Agent Start Rule

Every agent starts by reading:

1. `docs/AGENT_START_HERE.md`
2. `docs/FEATURE_MATRIX.md`
3. `docs/AI_DEVELOPMENT_WORKFLOW.md`
4. The specific issue, task, or PR description

Agents must not infer shipped status from file existence. Product status comes
from the feature matrix, tests, release docs, and executable checks.

## Required Change Flow

1. Define the task scope before editing files.
2. Work on a branch or scoped private commit, not directly on public `main`.
3. Update docs and tests when user-facing behavior, install flow, or feature
   status changes.
4. Run the focused tests for the changed area.
5. Run public safety gates for install, GitHub, or release work.
6. Merge only after required checks are green.
7. Sync public hardening back to private so private development does not fall
   behind public safety fixes.

## Required Public Release Flow

1. Private development branch reaches a candidate state.
2. Export or prepare a sanitized public snapshot.
3. Remove private notes, local caches, support bundles, Cloudflare/site secrets,
   unrelated project notes, personal artifacts, and private release history.
4. Run:

```powershell
python scripts\github_publish_preflight.py --json --strict --deep
python scripts\check_repo_hygiene.py --require-clean-worktree --strict --json
python -m pytest tests\test_public_release_surface.py tests\test_product_surface_copy.py tests\test_public_repo_guidance.py -q
```

5. Open a public PR to `main`.
6. Wait for GitHub Actions to pass.
7. Publish a GitHub Release with the Windows installer asset.
8. Verify the release asset exists and the README points to it.
9. Sync public hardening back into the private repo.

## Install UX Rule

The public install path is the GitHub Release installer asset. Do not publish
ZIP as the primary user path. Do not publish ZIP download as the primary user path.

Current expected public installer shape:

- GitHub Release tag with `ThomasSetup_*.exe`
- README download link to that installer
- First-run setup launched by the installer or launcher
- `support.cmd` for install failure bundles

## GitHub Rules

- Public GitHub should expose `main` as the only normal user branch.
- Public PRs target `main`.
- Required checks must include publish safety and robustness gates.
- Installer releases must use the Windows installer workflow.
- PRs touching release, installer, setup, networking, or GitHub configuration
  must run the public preflight.

## AI Guardrail Rules

- Do not bypass checks to make a change pass.
- Do not remove this workflow from agent instructions.
- Do not remove the workflow contract test unless replacing it with a stricter
  executable gate.
- Do not call Partial, Prototype, or Planned work finished.
- Do not add secrets, personal notes, generated support bundles, local caches,
  private website deployment details, or private changelog history.

## Enforcement

The workflow is enforced by:

- `.github/copilot-instructions.md`
- `.github/pull_request_template.md`
- `docs/AGENT_START_HERE.md`
- `scripts/check_ai_workflow_contract.py`
- `tests/test_ai_workflow_contract.py`
- GitHub Actions running the workflow contract and public release gates
