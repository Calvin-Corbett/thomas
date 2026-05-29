# Task Plan: gate-architecture-2026-05-26

- task_id: `gate-architecture-2026-05-26`
- owner: `claude`
- status: `active`
- problem_record: `plans/thomas/problems/gate-architecture-2026-05-26/PROBLEM.md`
- scope: `.github/workflows/, .github/CODEOWNERS, docs/SAFETY_ARCHITECTURE.md, docs/SIGNING_KEY_SETUP.md, docs/BRANCH_PROTECTION_SETUP.md, tests/test_native_auth_filesystem_guard.py, tests/test_gate_architecture_e2e.py, thomas/tools/filesystem.py (additive — extending existing _is_protected_runtime_path callers), CHANGELOG.md`
- created_at_utc: `2026-05-26T22:00:00+00:00`
- approved_by_human: the product owner (2026-05-26, this session — explicit directive in /goal)

## Objective

Land the 4-layer safety architecture from PROBLEM.md so that
`git commit --no-verify` becomes inert: the commit either gets rejected
locally (signing requires OS auth), or gets rejected at the remote
(branch protection + required status checks running the gates
server-side, plus signed-commit requirement).

Acceptance: an agent attempting `git commit --no-verify` cannot land
the resulting commit on `dev` or `main`. Documented end-to-end proof
in `docs/SAFETY_ARCHITECTURE.md`.

## Architecture (4 layers)

| Layer | What | Where it lives | Who can touch |
|---|---|---|---|
| 1 | Branch protection requires signed commits | GitHub repo Settings → Branches | the product owner (UI clickpath) |
| 2 | Signing key in OS keychain | Windows Credential Manager (Win Hello-protected) | the product owner (runbook) |
| 3 | Keychain access requires native OS auth | Windows Hello PIN/biometric prompt | OS-native (no software path) |
| 4 | GitHub Actions mirror of gates as required status checks | `.github/workflows/gates.yml` | claude (in scope) |

Plus 2 supporting pieces:

| Piece | What | Where | Who |
|---|---|---|---|
| CODEOWNERS | Route reviews of safety-critical paths to the product owner | `.github/CODEOWNERS` | claude (in scope) |
| Native-auth extension | Wrap protected-file write attempts with OS auth | `thomas/tools/filesystem.py` + new test | claude (additive only — won't modify existing `_is_protected_runtime_path` return semantics) |

## Scope boundaries

### What claude does (this PR)

- `.github/workflows/gates.yml` — new file, mirror of `scripts/forge/gates/*` as
  per-gate jobs (separate jobs so each is a markable required status check)
- `.github/CODEOWNERS` — new file
- `docs/SIGNING_KEY_SETUP.md` — the product owner's runbook for layer 2 (commands he runs)
- `docs/BRANCH_PROTECTION_SETUP.md` — the product owner's runbook for layer 1 + step 4 (UI clickpath)
- `docs/SAFETY_ARCHITECTURE.md` — mental-model doc (the *why* for future agents)
- `tests/test_native_auth_filesystem_guard.py` — coverage for the extended native-auth
- `tests/test_gate_architecture_e2e.py` — proof artifact for the `--no-verify` scenario
- `thomas/tools/filesystem.py` — additive extension of `_is_protected_runtime_path` callers to optionally consult `request_native_authorization` (gated by an explicit kwarg; default behavior unchanged)
- `CHANGELOG.md` — entry under `[Unreleased]`

### What the product owner does (out of band, gated by his hand)

- Run the signing-key setup commands from `docs/SIGNING_KEY_SETUP.md`
- Click through GitHub branch protection per `docs/BRANCH_PROTECTION_SETUP.md`
- Mark the new `gates.yml` jobs as required status checks
- Add the CODEOWNERS team/user mappings via the GitHub UI if needed (file alone routes review requests; UI enforcement is the second half)
- Merge the PR

### What claude does NOT touch (protected)

- `agent_safety.toml` — only the product owner/breakglass; we'll note the architecture
  shift in a follow-up by the product owner (see "Post-merge follow-ups" below)
- `.pre-commit-config.yaml` — same; local hooks stay as developer convenience
- `scripts/forge/gates/*` — enforcement scripts themselves stay untouched in
  this PR (the local-gate bypass cleanup is a *separate* task per PROBLEM.md
  "Bootstrap constraint" section — sequencing: only after server-side
  enforcement is live)
- `thomas/core/agent_presence.py` — protected runtime
- `thomas/tools/native_auth.py` — protected runtime; we extend *callers*, not the function itself

## Implementation sequence

### Phase 0 — Branch + workboard (no code yet)

1. Branch `claude/gate-architecture-2026-05-26` from current HEAD (`9013c5fc` on `claude/checkpoint-2026-05-26`).
2. Add WORKBOARD entries:
   - Active Tasks: `task_id=gate-architecture-2026-05-26; agent=claude; scope=<above>; summary=...; status=active`
   - Task Plans: pointer to this PLAN.md
   - Move problem record from `up_for_grabs` to `owner=claude; status=active`
3. Commit just the WORKBOARD + this PLAN.md (small, validates the gate stack works for the new branch).

### Phase 1 — Server-side enforcement (Layer 4)

4. Write `.github/workflows/gates.yml` with one job per gate script:
   - Each job: checkout, setup Python 3.12, install deps, run the single gate.
   - Use a `gate-deps` reusable step or matrix where shape allows (DRY without sacrificing per-gate visibility).
   - Triggers: `pull_request` to `dev`/`main`, `push` to `dev`/`main`.
   - Final aggregator job `gates-all-passed` with `needs: [<every gate job>]` for a single required-status-check name if the product owner prefers that over marking each individually.
5. Write `.github/CODEOWNERS`:
   ```
   # Safety-critical paths — the product owner must review changes
   /agent_safety.toml                @Calvin-Corbett
   /.pre-commit-config.yaml          @Calvin-Corbett
   /scripts/forge/gates/             @Calvin-Corbett
   /scripts/active_folders.py        @Calvin-Corbett
   /thomas/core/agent_presence.py    @Calvin-Corbett
   /thomas/tools/native_auth.py      @Calvin-Corbett
   /thomas/tools/windows_auth.py     @Calvin-Corbett
   /.github/workflows/gates.yml      @Calvin-Corbett
   /.github/CODEOWNERS               @Calvin-Corbett
   /docs/SAFETY_ARCHITECTURE.md      @Calvin-Corbett
   /docs/SIGNING_KEY_SETUP.md        @Calvin-Corbett
   /docs/BRANCH_PROTECTION_SETUP.md  @Calvin-Corbett
   ```
6. Smoke-test the workflow locally where possible: `gh workflow view gates.yml`, lint with `actionlint` if installed, `python -c "import yaml; yaml.safe_load(open('.github/workflows/gates.yml'))"`.

### Phase 2 — the product owner's runbooks (Layers 1, 2, 3)

7. Write `docs/SIGNING_KEY_SETUP.md`:
   - Two options: SSH-based (modern, simpler, fewer moving parts) vs GPG (broader compat).
   - Recommend SSH signing (Git 2.34+) because the key can be `ssh-keygen -t ed25519` and stored as a normal SSH key, with `git config commit.gpgsign true` + `gpg.format ssh` + `user.signingkey ~/.ssh/id_ed25519.pub` + `gpg.ssh.allowedSignersFile` for verification.
   - Windows Credential Manager + Windows Hello path: enable Win Hello for the key passphrase via Windows-managed PKCS#11 token or `git-credential-manager` integration.
   - Explicit PowerShell snippets the product owner runs.
   - Verification step: `git commit --allow-empty -m "signing test"` should pop Win Hello PIN; `git log --show-signature -1` should show "Good signature".
8. Write `docs/BRANCH_PROTECTION_SETUP.md`:
   - Step-by-step UI clickpath for `dev` and `main` on `thomas-dev` and `thomas` repos.
   - Settings → Branches → Add rule → branch name pattern `dev` (then again for `main`).
   - Check: "Require a pull request before merging" (with "Require approvals: 1" and "Require review from Code Owners").
   - Check: "Require status checks to pass before merging" → search for `gates-all-passed` (or the individual gate job names — pick one approach).
   - Check: "Require signed commits".
   - Check: "Require linear history".
   - Check: "Do not allow bypassing the above settings" (including admins — the product owner can still bypass via direct repo settings but not via casual commits).
   - Uncheck: "Allow force pushes" and "Allow deletions".
   - Verification: try pushing an unsigned commit to a new branch and opening a PR; merge button should be disabled.

### Phase 3 — Native-auth extension (additive)

9. Inspect `thomas/tools/filesystem.py::_is_protected_runtime_path` and the
   callers (likely `fs_write_file`, `diff_apply_patch`, etc.):
   - Current behavior: return True → refuse the write.
   - Extended behavior: if a new opt-in kwarg `allow_native_auth_override=True`
     is set AND `request_native_authorization` returns True, allow the write
     and emit an audit log. Default kwarg stays `False`, so existing call
     sites' behavior is unchanged.
   - This is preparation for future use; the workflow + branch protection
     are the primary fix. Native-auth filesystem extension is the secondary
     defense-in-depth piece for non-git protected-path manipulation paths.
10. Write `tests/test_native_auth_filesystem_guard.py`:
    - Default behavior unchanged (refuses without flag).
    - With flag + monkeypatched `request_native_authorization` returning True:
      write succeeds, audit log fires.
    - With flag + monkeypatched returning False: write refuses.

### Phase 4 — E2E proof + docs

11. Write `tests/test_gate_architecture_e2e.py`:
    - Simulate the `--no-verify` scenario by reading the workflow yaml,
      asserting the required gate jobs exist, the signed-commit rule is
      documented, the CODEOWNERS file routes the protected paths.
    - Not a true end-to-end test (that requires pushing to GitHub), but a
      contract test that the *artifacts* needed for end-to-end enforcement
      are present and correctly wired.
12. Write `docs/SAFETY_ARCHITECTURE.md`:
    - The 4-layer model, drawn out as ASCII diagram.
    - The 2026-05-26 incident reference (the proven bypass that motivated this).
    - The "what `--no-verify` does now" walkthrough.
    - The "what's still bypassable and why we accept it" honest section
      (e.g., the product owner's own machine compromise, GitHub itself compromised).
    - Post-merge follow-ups list (the local-gate env-var bypass cleanup,
      now safe to do because server-side is live).

### Phase 5 — Land the PR

13. Update `CHANGELOG.md` `[Unreleased]` with a `### Security` entry.
14. Push branch to `dev-origin`, open PR titled
    `safety: server-side gate enforcement + signed commits architecture`
    targeting `dev`.
15. PR body explains: what changed, what the product owner needs to do post-merge
    (the runbook steps), test plan, and a link to PROBLEM.md.
16. Trailer: `Thomas-Agent: claude`.

## Acceptance criteria

### Must pass before PR opens

- [ ] `.github/workflows/gates.yml` exists and `python -c "import yaml; yaml.safe_load(...)"` parses cleanly
- [ ] `.github/CODEOWNERS` exists with all listed paths routed to `@Calvin-Corbett`
- [ ] `docs/SIGNING_KEY_SETUP.md`, `docs/BRANCH_PROTECTION_SETUP.md`,
      `docs/SAFETY_ARCHITECTURE.md` all exist and pass markdown lint
- [ ] `tests/test_native_auth_filesystem_guard.py` passes locally
- [ ] `tests/test_gate_architecture_e2e.py` passes locally
- [ ] No existing test broken (`pytest -q tests/test_guarded_tools_native_auth.py tests/test_guarded_tool_runner.py`)
- [ ] CHANGELOG entry under `[Unreleased]` describes the security change
- [ ] All pre-commit gates pass without `--no-verify` (zero breakglass usage)

### Must pass post-merge (the product owner's work, not in this PR)

- [ ] `dev` and `main` branch protection rules enabled with: signed commits,
      required status checks (the gates.yml jobs), CODEOWNERS review required,
      no force-push, linear history
- [ ] the product owner's local git configured with signing key + Win Hello-protected access
- [ ] Test commit from the product owner's machine pops Win Hello PIN dialog
- [ ] An unsigned commit pushed to a test branch → merge button disabled on PR

## Test plan

Local (in this PR, must pass before PR opens):
- `python -m pytest -q tests/test_native_auth_filesystem_guard.py`
- `python -m pytest -q tests/test_gate_architecture_e2e.py`
- `python -m pytest -q tests/test_guarded_tools_native_auth.py tests/test_guarded_tool_runner.py` (regression check)
- `python -c "import yaml; yaml.safe_load(open('.github/workflows/gates.yml'))"`
- `python scripts/bible_status.py` — must stay green
- pre-commit run on staged files — all gates pass, zero `--no-verify`

Post-merge (the product owner's verification, documented in SAFETY_ARCHITECTURE.md):
- Pick any safe test branch; `git commit --no-verify -m "test"` on the product owner's machine.
- If the product owner has the new git config: commit fails locally because signing requires Win Hello and the `--no-verify` skipped the hook that would have prompted.
- If signing succeeds (the product owner approves the prompt): push to test branch on dev-origin, open PR → GitHub workflow re-runs the gates → if gates pass it would merge, if gates fail merge blocked. Either way, the `--no-verify` is no longer a free pass.

## Risks + mitigations

1. **Risk**: workflow takes too long to run on every PR, slows iteration.
   **Mitigation**: per-gate jobs run in parallel by default; total wall time
   is the slowest single gate (~5 min), not the sum. If some gates are slow
   (e.g., `boot_smoke_gate.py`), they go in a separate slower-tier job that's
   still required but doesn't block per-gate fail-fast.

2. **Risk**: SSH signing setup is finicky on Windows. the product owner loses an hour
   debugging Win Hello + PKCS#11 + git config interactions.
   **Mitigation**: SIGNING_KEY_SETUP.md includes a tested fallback to
   git-credential-manager-based SSH signing without Win Hello (still
   passphrase-protected, just typed instead of biometric). Honest tradeoff
   noted: passphrase-typed is software-recoverable while Win Hello is
   hardware-bound.

3. **Risk**: branch protection lockout — the product owner sets it up too strict, can't
   push hotfixes to dev. **Mitigation**: BRANCH_PROTECTION_SETUP.md explicitly
   leaves admin-bypass enabled (the product owner as repo owner can override in
   emergencies). The rule is for agents and casual flow, not for the product owner's
   own breakglass on dev.

4. **Risk**: existing `claude/checkpoint-2026-05-26` branch carries
   un-merged work that conflicts with this hardening PR.
   **Mitigation**: this branch is downstream of the checkpoint (branches
   off `9013c5fc`), so it inherits not conflicts with. PR target is `dev`,
   so the conflict surface is only what dev has that checkpoint doesn't.

5. **Risk**: the deeper change — making `--no-verify` actually inert — could
   surprise developers who depended on it as escape hatch.
   **Mitigation**: SAFETY_ARCHITECTURE.md documents the new model
   explicitly; agent_safety.toml gets a header comment (in a follow-up by
   the product owner) noting "server-side enforcement is the safety; local hooks are
   convenience". The intent is clear from the start.

## Post-merge follow-ups (separate tasks)

- Remove the env-var/CLI-flag bypasses from local gates (per PROBLEM.md
  "Bootstrap constraint" — only safe to do AFTER server-side enforcement
  is live).
- Update `agent_safety.toml` header comment to reflect the new mental model
  ("local gates are developer convenience; server-side enforcement is the
  source of truth"). the product owner's work since `agent_safety.toml` is in his
  protected-files list.
- Audit any other agent-reachable bypass paths (Python `os.remove` on
  protected files, `shutil.rmtree` on protected dirs, etc.) and wrap them
  with `request_native_authorization`.
- Periodic re-audit of `.github/workflows/gates.yml` to ensure new local
  gates also get the server-side mirror — automate via a meta-gate that
  diffs `scripts/forge/gates/` listing against workflow job count.

## References

- [PROBLEM.md](../../problems/gate-architecture-2026-05-26/PROBLEM.md) — full spec, especially "THE DEEPER FINDING" and "Proposed implementation: OS-auth-gated signing + server-side enforcement"
- `thomas/tools/native_auth.py` — existing OS auth primitive (3 platforms covered)
- `thomas/agent/guarded_tools.py:170` — the existing native-auth call site (tool-level)
- `.github/workflows/robustness-gates.yml` — existing partial mirror (we keep this; gates.yml is the per-gate split that's branch-protection-compatible)
- `agent_safety.toml [runtime_protection]` — the hardcoded protected-paths list this layer extends with native-auth
- [the product owner's 2026-05-26 chat] — origin of "what if the user has to input a password?" framing
