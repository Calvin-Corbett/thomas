# Branch Protection Setup (the product owner's UI clickpath)

This is the runbook for the product owner to enable GitHub branch protection on
`dev` and `main` — **layer 1** of the safety architecture (see
[SAFETY_ARCHITECTURE.md](SAFETY_ARCHITECTURE.md)).

**Time**: ~10 minutes total (5 per repo).

**Prerequisites**:
- Signed commits must be configured first ([SIGNING_KEY_SETUP.md](SIGNING_KEY_SETUP.md)).
- The `.github/workflows/gates.yml` workflow must have run at least once
  on dev (so GitHub knows the check names exist to require). Pushing this
  PR runs it once.

**What this does**: Locks `dev` and `main` so:
- Direct pushes are rejected (PR required).
- Force-pushes are rejected.
- Unsigned commits are rejected.
- The `gates-required` workflow must pass to merge.
- A Code Owner (the product owner, per [CODEOWNERS](../.github/CODEOWNERS)) must
  approve changes to safety-critical paths.

After this runs, the path "agent uses `git commit --no-verify` then pushes
to dev" is closed end-to-end.

---

## Repo 1: `<your-account>/<private-dev-repo>` (private dev repo)

### Step 1. Open branch protection settings

1. Open https://github.com/<your-account>/<private-dev-repo>/settings/branches
2. Click **Add branch protection rule** (or **Edit** if a rule for `dev`
   already exists).

### Step 2. Configure the rule for `dev`

**Branch name pattern**: `dev`

**Check these boxes** (top-to-bottom):

- [x] **Require a pull request before merging**
  - [x] Require approvals: **1**
  - [x] Dismiss stale pull request approvals when new commits are pushed
  - [x] **Require review from Code Owners**
  - [ ] Require approval of the most recent reviewable push (optional)
  - [x] Restrict who can dismiss pull request reviews
    - Add: **Calvin-Corbett** (you can dismiss your own reviews)

- [x] **Require status checks to pass before merging**
  - [x] Require branches to be up to date before merging
  - In the search box, find and check:
    - [x] `gates-required`
    - [x] `signed-commits-check`
    - [x] `protocol-parity` (existing job from robustness-gates.yml)
    - [x] `codebase-auto-checks` (existing)
    - [x] `security-regression (3.10)` and `(3.12)` (existing matrix jobs)
    - [x] `docker-smoke` (existing)
    - [x] `required-gates` (existing)
  - (If a check name isn't in the dropdown, the workflow hasn't run
    yet on `dev`. Push something trivial to trigger it, then re-edit.)

- [x] **Require conversation resolution before merging**

- [x] **Require signed commits**
  - (This is the layer-1 + layer-2 + layer-3 enforcement combined.)

- [x] **Require linear history**
  - (Forces squash or rebase merges; prevents merge-commit noise.)

- [x] **Require deployments to succeed before merging** — leave unchecked
  (we don't gate on deployment status).

- [x] **Lock branch** — leave unchecked (we want PRs to work).

- [x] **Do not allow bypassing the above settings**
  - **IMPORTANT**: This is the rule that makes the protection actually
    enforce. Without it, repo admins (the product owner) can bypass via "Admin"
    button. With it, even the product owner uses the PR flow.
  - the product owner can still toggle this off in an emergency by editing this
    rule. That edit is logged in the repo audit log.

- [ ] **Restrict pushes that create matching branches** — leave unchecked.

- [ ] **Allow force pushes** — **leave unchecked** (this disables force-push).

- [ ] **Allow deletions** — **leave unchecked** (this disables branch deletion).

Click **Create** (or **Save changes**).

### Step 3. Verify

Try to push directly to `dev`:

```powershell
cd C:\Users\corbe\Thomas
git checkout dev
git commit --allow-empty -m "test direct push"
git push dev-origin dev
# Expected: rejected with "protected branch hook declined"
```

Reset:
```powershell
git reset --hard HEAD~1
```

Done with `thomas-dev` `dev`.

### Step 4. Repeat for `main` on thomas-dev (same repo, different branch)

If `thomas-dev` has a `main` branch you also want protected (typical for
public-sync), add a second rule with branch pattern `main` and the same
settings.

If `thomas-dev` doesn't have a `main` branch (everything happens on
`dev` and you only push to the public `thomas` repo), skip this and
move on.

---

## Repo 2: `Calvin-Corbett/thomas` (public repo)

### Step 1. Open branch protection settings

1. Open https://github.com/Calvin-Corbett/thomas/settings/branches
2. Click **Add branch protection rule** (or **Edit** for `main`).

### Step 2. Configure the rule for `main`

**Branch name pattern**: `main`

Same checks as the dev rule above, except:

- For status checks, only require what runs on the public repo. Check:
  - [x] `gates-required` (if you've copied gates.yml to the public repo)
  - [x] `signed-commits-check`
  - Any other workflows that run on `main` PRs in the public repo.

- **Require signed commits**: [x] (same as dev)

- **Do not allow bypassing the above settings**: [x]

- **Allow force pushes / deletions**: both unchecked

Click **Save changes**.

---

## What this enables (end-to-end)

After both repos are configured:

| Agent action | Result |
|---|---|
| `git commit -m "x"` (with signing) | Signed commit; passes |
| `git commit --no-verify -m "x"` (with signing) | Signed commit (signing isn't a hook); passes server-side checks if gates pass; but local hooks bypassed locally — still passes |
| `git commit --no-verify -m "x"` (signing not configured for agent) | Unsigned commit; push to dev/main rejected by branch protection |
| `git push --force dev-origin dev` | Rejected (force-push disabled) |
| Direct push to `dev` (bypassing PR) | Rejected (PR required) |
| PR with a failing gate | Rejected (status check required) |
| PR touching `agent_safety.toml` without Code Owner approval | Rejected (Code Owner review required) |

The `--no-verify` path that Claude exploited on 2026-05-26 is closed:
even if an agent signs with the product owner's key (which requires Windows Hello),
the gate check still runs server-side via `gates-required`. Both must
pass for the merge to be allowed.

---

## Troubleshooting

### "Required status check 'gates-required' not found"

The workflow hasn't run yet on `dev`. Push a trivial commit to a feature
branch and open a PR targeting `dev`; that triggers the workflow.
Once it's run once, the check name appears in the dropdown.

### "I can't push to dev — I'm locked out"

Open the branch protection rule UI, temporarily uncheck
"Do not allow bypassing the above settings", do the push, then
re-check it. Or use the PR flow.

### "An agent created a PR that bypassed CODEOWNERS"

Verify in branch protection: "Require review from Code Owners" must
be checked. If it is, GitHub blocks merge until the product owner (the listed
owner for those paths) approves. If you see merges happening without
your review on safety-critical paths, the CODEOWNERS path patterns
might not be matching — check `.github/CODEOWNERS` syntax.

### "Some checks I want to require aren't in the dropdown"

GitHub only shows checks that have run at least once on the target
branch. Open a draft PR or push a probe commit to trigger the workflow,
wait for it to finish, then re-open branch protection settings.

### Repo audit log

To see all branch protection changes:
https://github.com/<your-account>/<private-dev-repo>/settings/audit-log

Filter by `branch.protection` to see who edited the rules and when.

---

## Next step

After both repos are configured:
1. Try the end-to-end test in [SAFETY_ARCHITECTURE.md § Verification](SAFETY_ARCHITECTURE.md#verification).
2. Notify Codex (and any other agents) that the new safety architecture
   is live by posting on the workboard.
3. The follow-up task (post-merge) is to remove the env-var bypasses
   from local gates (per PROBLEM.md "Sequencing for the architectural
   fix (revised)" step 5). This is safe to do now that server-side
   enforcement is live.
