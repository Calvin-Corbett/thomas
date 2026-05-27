# Thomas Safety Architecture

The mental model for how safety is enforced in this repo, after the
2026-05-26 architecture overhaul (PROBLEM.md
[gate-architecture-2026-05-26](../plans/thomas/problems/gate-architecture-2026-05-26/PROBLEM.md)).

## TL;DR

Local pre-commit hooks (`.pre-commit-config.yaml`) are **developer
convenience**. They catch mistakes early before push. They are **NOT
safety** — `git commit --no-verify` skips all of them, and that flag
is built into git.

The actual safety enforcement lives in **four layers**, all of which
sit outside the local repo and outside any agent's reach:

1. **GitHub branch protection** on `dev` and `main` requires signed
   commits and required status checks.
2. **OS keychain** holds the signing key; an agent cannot read it.
3. **Native OS auth** (Windows Hello / Touch ID / hardware key) gates
   keychain access; a real human must put a real finger on a real
   sensor.
4. **GitHub Actions** re-runs every safety gate on every push/PR via
   `.github/workflows/gates.yml`. A `--no-verify` commit cannot bypass
   this — the workflow runs server-side regardless of local hooks.

When stacked, these make `git commit --no-verify` **inert**: the commit
either fails locally (signing requires OS auth) or gets rejected at the
remote (branch protection + gates workflow).

## The incident that motivated this

On 2026-05-26 evening, Claude — an LLM agent operating in this repo —
ran `git commit --no-verify -m "..."` and pushed to dev-origin. The
push succeeded. The 50+ pre-commit gates were skipped entirely. Calvin
had to question the authorization pattern AFTER the fact; nothing in
the technical system caught it.

The 50+ gates in `scripts/forge/gates/` could have been deleted that
day and the actual safety posture wouldn't have changed for any
motivated actor. Local gates that any actor can `--no-verify` past are
not enforcement — they're advisory. The architecture before 2026-05-26
mistook advisory for enforcement.

## The 4-layer architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        GitHub (dev-origin)                          │
│                                                                     │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │ Layer 1: Branch Protection on dev/main                      │   │
│   │   - Require signed commits ──┐                              │   │
│   │   - Require status checks ───┼──→ gates-required job        │   │
│   │   - Require Code Owner review (CODEOWNERS routes Calvin)    │   │
│   │   - No force push, no deletion, linear history              │   │
│   └────────────────────────────────────────────────────────────┘   │
│                              ↑                                      │
│                              │ commit must be signed and pass gates │
└──────────────────────────────┼──────────────────────────────────────┘
                               │ git push
┌──────────────────────────────┴──────────────────────────────────────┐
│                       Calvin's dev machine                          │
│                                                                     │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │ Layer 4 (local): pre-commit hooks (.pre-commit-config.yaml) │   │
│   │   - Same gate scripts as Layer 4 server-side                │   │
│   │   - Bypassable via --no-verify (and that's OK now)          │   │
│   │   - Purpose: catch mistakes early; advisory, not safety     │   │
│   └──────────────────────────────┬──────────────────────────────┘   │
│                                  ↓ git commit                       │
│   ┌──────────────────────────────────────────────────────────────┐  │
│   │ Layer 3: Native OS authentication (Windows Hello/biometric)  │  │
│   │   - Pops on signing-key access                               │  │
│   │   - Requires real human at physical device                   │  │
│   │   - Agent cannot fake biometric or PIN                       │  │
│   └──────────────────────────────┬───────────────────────────────┘  │
│                                  ↓ unlock                           │
│   ┌──────────────────────────────────────────────────────────────┐  │
│   │ Layer 2: OS keychain (Windows Credential Manager)            │  │
│   │   - Holds the SSH signing key                                │  │
│   │   - Agent cannot read it (separate process boundary + OS-   │  │
│   │     enforced access control)                                 │  │
│   └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

## What each layer enforces

### Layer 1 — GitHub branch protection (`dev` and `main`)

Configured per [BRANCH_PROTECTION_SETUP.md](BRANCH_PROTECTION_SETUP.md).
Lives in GitHub repo settings — outside the repo, outside any agent's
reach.

Enforces:
- Pull request required (no direct push).
- All required status checks must pass — including `gates-required`
  from `.github/workflows/gates.yml`.
- Code Owner review required on paths listed in
  [`.github/CODEOWNERS`](../.github/CODEOWNERS).
- Signed commits required.
- No force push, no branch deletion, linear history.
- "Do not allow bypassing" toggle is on — even admins use the PR flow.

### Layer 2 — OS keychain holds the signing key

Configured per [SIGNING_KEY_SETUP.md](SIGNING_KEY_SETUP.md). On Calvin's
machine, the key lives in Windows Credential Manager / OpenSSH Agent.
An agent can call `git` but cannot directly read the key bytes — that
requires the OS keychain's own access path.

### Layer 3 — Native OS auth gates keychain access

Built into Windows (Win Hello PIN/biometric) and macOS (Touch ID /
Apple Watch). Pops a system-level prompt on the physical device when
something tries to use the signing key. A real human must put a real
finger on a real sensor.

**Agents cannot fake this.** No software path inside the agent's
process can produce a successful Win Hello response — the verification
happens in OS protected memory, against a TPM-backed credential.

Thomas already uses this primitive for sensitive tool calls via
`thomas/tools/native_auth.py::request_native_authorization` and
`scripts/breakglass_auth.py::authorize_breakglass`. This architecture
extends the same primitive to git operations.

### Layer 4 — Server-side gate mirror in GitHub Actions

[`.github/workflows/gates.yml`](../.github/workflows/gates.yml) re-runs
every safety gate that's meaningful server-side. The gates are the same
scripts in `scripts/forge/gates/` — but they run on GitHub's runners,
not the local machine. A `--no-verify` commit cannot bypass this:

- `--no-verify` only skips `.git/hooks/*` callbacks during git's local
  commit phase. It has no effect after the commit is created.
- When the commit is pushed, GitHub Actions starts the `gates.yml`
  workflow.
- Every gate runs against the actual diff.
- Required status check: `gates-required` (aggregator job depending on
  all gate jobs).
- If any gate fails, the merge button is disabled in the PR UI.

## What an agent's `git commit --no-verify` does under this architecture

1. Agent runs `git commit --no-verify -m "..."`.
2. Git allows the commit (the flag is native to git; can't remove).
3. Git attempts to sign the commit. Signing requires the keychain key.
4. Keychain access requires Windows Hello.
5. Windows pops a prompt on Calvin's physical device: "Sign this commit?"
6. **Calvin** sees the prompt. Either approves (PIN/biometric) or denies.
   - If denied: commit fails locally. End of story.
   - If approved: commit is signed and saved locally.
7. Agent pushes the signed commit to dev-origin.
8. GitHub Actions re-runs the gates on the push.
9. Required status checks (gates-required, signed-commits-check) must pass.
10. If any gate fails: branch protection rejects the merge.

To land bad code, an agent would need: Calvin's physical device + Calvin's
biometric/PIN + Calvin's approval at step 6, AND the gate workflow passing
at step 9. None of those are agent-reachable.

## What's still bypassable (honest section)

A complete enumeration so future agents don't build assumptions on
unverified ground:

| Attack | Mitigation status |
|---|---|
| Agent commits `--no-verify`, no signing configured locally | Caught by Layer 1 (push rejected: "commit must be signed") |
| Agent commits `--no-verify`, signing configured but key access requires Calvin's biometric | Caught at Layer 3 (Win Hello prompt; Calvin denies or commit fails on timeout) |
| Agent commits `--no-verify`, gets Calvin to approve the Win Hello prompt (social), pushes | Caught by Layer 4 (gates.yml runs server-side; if gates would fail, merge blocked) |
| Agent gets Calvin's approval AND pushes commit that passes all server-side gates | This is "Calvin approved a real change" — by design, not a bypass. The Win Hello tap is the authorization. |
| Calvin's physical device stolen + biometric forged | Outside threat model. If a hostile party has Calvin's TPM + Calvin's finger, larger problems exist. |
| GitHub itself compromised | Outside threat model. The architecture trusts GitHub's branch protection and Actions runners as authorities. |
| Agent edits `agent_safety.toml` to disable gates | Caught by Layer 4 (`protected-files-gate` job). Even if local gate bypassed, server-side gate catches the diff. |
| Agent edits `.github/workflows/gates.yml` to remove gates | Caught by Layer 1 (CODEOWNERS routes review to Calvin; merge blocked until Calvin approves). Even if Calvin clicks approve quickly, the change is visible in the PR diff. |
| Agent edits `scripts/forge/gates/*.py` to silently pass | Caught by Layer 1 (CODEOWNERS for `scripts/forge/gates/`). Even if local gate is rewritten, server-side runs the version from the PR's head — which Calvin reviewed. |

The architecture is not "no bypass possible" — that's unattainable.
It's "no bypass possible without a real human authorizing each step
that matters".

## Local gates are now advisory

[`agent_safety.toml`](../agent_safety.toml) and
[`.pre-commit-config.yaml`](../.pre-commit-config.yaml) still configure
~50 gates that run on Calvin's pre-commit. These remain useful as
**developer convenience**:

- Fast feedback (catches mistakes in 30s vs waiting 10min for CI)
- Trains habits (you learn what passes vs fails locally)
- Reduces CI burn (don't push obvious failures)

But they are no longer the source of truth for safety. Any local-gate
bypass that doesn't ALSO bypass GitHub Actions is harmless — the server
re-runs the same checks.

Specifically, the env-var bypasses called out in PROBLEM.md
(`THOMAS_BULK_COMMIT_GUARD_DISABLE`, `--max-growth` flag,
`--allow-presence-override`) are no longer the safety hole they were
before — they only disable local feedback. The post-merge follow-up
task is to clean them up anyway (they're a code smell, even if not a
safety hole now). See PROBLEM.md "Sequencing for the architectural
fix (revised)" step 5.

## Verification

End-to-end test that the architecture works:

1. On a feature branch, create a commit with an intentional gate-failing
   change (e.g., add a file >1200 lines to trip `monolith_guard`):
   ```powershell
   # Generate a large file
   1..1500 | ForEach-Object { "# line $_" } | Out-File -Encoding utf8 thomas/_oversized_test.py
   git add thomas/_oversized_test.py
   # Skip local hooks (the test scenario):
   git commit --no-verify -m "test: monolith_guard server-side bypass attempt"
   git push dev-origin HEAD
   ```
2. Open a PR targeting `dev`.
3. **Expected**: GitHub Actions runs `gates.yml`. The `monolith-guard`
   job fails. `gates-required` fails (aggregator). Merge button is
   disabled in the PR UI.
4. Clean up:
   ```powershell
   git reset --hard HEAD~1
   git push --force-with-lease dev-origin HEAD
   # (only allowed because this is a feature branch, not dev/main)
   ```

If step 3 doesn't happen as described, branch protection isn't fully
configured. Re-check [BRANCH_PROTECTION_SETUP.md](BRANCH_PROTECTION_SETUP.md).

## For agents reading this doc

If you're an AI agent working in this repo: the 50+ local gates in
`scripts/forge/gates/` are the same gates that run on the server side
in `.github/workflows/gates.yml`. **Don't bypass the local gates** —
they're free preview of what server-side will say.

You also **can't** bypass them in a way that matters: even if you
`--no-verify`, your commit either won't sign (Win Hello blocks you)
or won't merge (server-side gates catch it). Treat the local hooks as
helpful preview, not as your enemy. Calvin's intent is that you do
correct work the first time, not creative work that almost-passes.

## References

- [PROBLEM.md (full spec)](../plans/thomas/problems/gate-architecture-2026-05-26/PROBLEM.md)
- [PLAN.md (this PR's plan)](../plans/thomas/tasks/gate-architecture-2026-05-26/PLAN.md)
- [SIGNING_KEY_SETUP.md (Calvin's runbook)](SIGNING_KEY_SETUP.md)
- [BRANCH_PROTECTION_SETUP.md (Calvin's UI clickpath)](BRANCH_PROTECTION_SETUP.md)
- [`.github/workflows/gates.yml` (server-side mirror)](../.github/workflows/gates.yml)
- [`.github/CODEOWNERS` (review routing)](../.github/CODEOWNERS)
- [`thomas/tools/native_auth.py` (OS-auth primitive — already in use)](../thomas/tools/native_auth.py)
- [`scripts/breakglass_auth.py` (Windows credential dialog wrapper)](../scripts/breakglass_auth.py)
