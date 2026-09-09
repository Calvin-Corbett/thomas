# Thomas Engineering-Pipeline Practices

The canonical "how to branch, commit, land, and not create a mess" guide. This
replaces the tribal *one-worktree-per-session* recipe that previously lived only
in agent memory and was the root of the branch/worktree sprawl.

## TL;DR

- **Work on a topic branch in the MAIN checkout.** Worktrees are OPTIONAL now —
  use one only for genuine parallelism, not because you have to.
- **Land via `dev_land` / `thomas ship`.** Landing auto-reaps the local branch +
  its worktree, so nothing is left behind.
- **Run `tidy_refs` to sweep backlog.** It only reaps what's provably safe.
- **Two kinds of gate.** Security gates hard-block (and that's correct). Hygiene
  gates have sanctioned escape valves — use the trailer, not a fight.

---

## 1. Why the sprawl happened (so it doesn't recur)

The chain was: a historical **commit jam** (the pre-commit guard used to rewrite the
*tracked* `WORKBOARD.md` mid-commit → stash conflicts in a shared checkout) made the
shared main checkout unsafe for back-to-back commits. The workaround was *one
worktree per agent session* — and **that workaround was the sprawl**. Then squash-merge
orphaned each local branch (its commits are never ancestors of `dev`, so `git branch -d`
can't reap it), and nothing tore down local branches or worktrees. Over weeks: ~50
branches / ~31 worktrees.

**The jam is now closed** (verified: the pre-commit `guard-staged` path writes only the
gitignored `runtime/coordination/active_folders.json`, never the tracked board). So the
premise behind per-session worktrees is gone. The sprawl was legacy backlog, not an
ongoing necessity.

## 2. The branch/commit/land loop (do this)

```
git switch -c claude/<task>-<YYYY-MM-DD> dev   # topic branch off dev, in the MAIN checkout
# ...edit, test (ruff + pytest)...
python scripts/crew/brief/commit.py            # or git commit — gates run
python scripts/forge/ship.py                   # or dev_land.py — land + AUTO-REAP local branch+worktree
```

- A separate worktree is justified ONLY when you need true parallel checkouts (two
  builds at once). It is no longer required just to commit safely.
- Landing reaps the local branch + worktree by default (`dev_land --keep-local` to opt
  out). Don't hand-create throwaway branches you won't land.

## 3. Ref lifecycle (three timescales)

| When | Mechanism | What it does |
|---|---|---|
| On land | `dev_land._teardown_local_refs` (default-on) | reaps the landed branch + its worktree |
| On demand | `python scripts/forge/tidy_refs.py [--apply]` | sweeps clean worktrees + merged/fully-on-remote branches; **never** touches local-only work or dirty worktrees |
| Salvage | `git update-ref refs/tags/archive/<branch> <sha>` before a risky delete | archive tip as a recoverable tag |

`tidy_refs` is intentionally conservative: it reaps only branches that are ancestors of
the base or fully contained in their upstream (recoverable via fetch). Branches with
local-only commits, no upstream, or a dirty worktree are **reported, never deleted** —
those need a human call.

## 4. Two kinds of gate — don't fight the wrong one

**Security invariants (hard-block by design — do NOT try to route around):**
secret scan, `enforcement_integrity` (anti-tamper on gate scripts), `protected_files_gate`,
architecture import rules. Editing a protected/enforcement file legitimately requires the
owner's native-auth (Windows Hello) tap and a manifest re-bless
(`python scripts/forge/gates/enforcement_integrity.py --generate-manifest`). That tap is
the human-in-the-loop, not a bug.

**Hygiene/coordination heuristics (have sanctioned escape valves — use them):**
- `commit_growth_guard` (new file > 300 lines): land with a
  `Thomas-Commit-Growth-Approved: <reason>` trailer, or split the file. Don't disable it.
- protected-file edits in a burst: turn on **QuickBuilder**
  (`python scripts/quickbuilder_toggle.py on`) — it waives the breakglass cooldown/quota
  while keeping the single per-commit tap.
- A batch of gate-maintenance edits: open the breakglass approval window once, make all
  the edits, regenerate the manifest once — one tap for the batch.

## 5. Health checks

- `python scripts/forge/tidy_refs.py` — dry-run sprawl report (what would be reaped).
- `python scripts/bible_status.py` — repo-quality health.
- (Proposed) `thomas doctor` — gate-interpreter check, worktree/branch budget,
  breakglass audit, manifest freshness in one screen.

## 6. Known-by-design friction (working as intended)

These look like bugs but are deliberate; the escape valve, not a code change, is the answer:

- **Protected-file edit needs a Windows-Hello tap** — the intended human gate. QuickBuilder
  waives only the cooldown, never the tap.
- **No self-authored approval trailer in local pre-commit** — a plaintext trailer the
  commit author writes would be forgeable; local approval stays native-auth. A tap-free
  local trailer would require server-side branch protection + CODEOWNERS or an
  out-of-worktree HMAC token.
- **Gate fix needs a human manifest re-bless** — anti-tamper by design; an agent that could
  silently re-bless a gate it just edited defeats the whole control.
