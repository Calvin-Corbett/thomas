# The sprawl curve, measured

Plan: `docs/superpowers/plans/2026-08-27-branch-equilibrium.md`, Task 3.
Analyzer: `scripts/forge/sprawl_history.py` (read-only; see its module
docstring for the full source-by-source honesty accounting). Tests:
`tests/test_the_sprawl_curve_marks_what_it_cannot_see.py`.

**Every number below is regenerable.** Run:

```
python scripts/forge/sprawl_history.py
python scripts/forge/sprawl_history.py --json
```

against this repo, right now, and you get the table and JSON this document
was written from (only `generated_at` and the "measured, this run" anchor's
exact unpushed count will differ, because time keeps moving and you keep
committing). Nothing in this document is a number this analyzer cannot
reproduce. Where a number cannot be reproduced — because the git state that
produced it is gone — it is marked **CITED**, not measured, with its exact
source named, both here and in the analyzer's own `anchors` output.

---

## What you asked

You asked why your prior fixes to branch sprawl — advisory rules, a
janitor, a squash, a custodian — each failed to move the number, and asked
for a way to prove it with data rather than a story. This is that proof, to
the extent the repository's own history can support one. It cannot support
all of it — see "What the data cannot show" below, stated before the
verdicts, not after, so it isn't mistaken for a footnote.

---

## The curve

Weekly, since 2026-05-01 (`--since` is a flag if you want a different
window). `rem-1st-seen` is a lower-bound count of remote branches this
checkout first recorded that week (via `.git/logs/refs/remotes/dev-origin/*`,
read directly, not fetched). `gy-branch`/`gy-file` are graveyard deaths
**recorded** that week (see the caveat below — this is a recording date, not
always a death date). `stash`/`wtree` are archive snapshots whose *original*
commit (not archival) date falls in that week. `live-local`/`unpushed` are
`unknown` except at the three anchor points this analyzer can actually
source.

```
week         live-local  unpushed   rem-1st-seen  gy-branch  gy-file  stash  wtree   milestone
2026-05-01   unknown     unknown    0             0          0        1      0
2026-05-08   unknown     unknown    0             0          0        0      0
2026-05-15   unknown     unknown    1             0          0        1      0
2026-05-22   unknown     unknown    4             0          0        7      0
2026-05-29   unknown     unknown    4             0          0        1      0
2026-06-05   unknown     unknown    19            0          0        1      1
2026-06-12   unknown     unknown    9             0          0        3      0
2026-06-19   unknown     unknown    10            0          0        5      0
2026-06-26   unknown     unknown    38            0          0        2      0
2026-07-03   unknown     unknown    0             0          0        0      0
2026-07-10   unknown     unknown    6             0          0        0      0
2026-07-17   unknown     unknown    3             0          0        38     15      branch_custodian.py lands (thomas consolidate)
2026-07-24   unknown     unknown    14            0          0        1      0
2026-07-31   unknown     unknown    39            0          0        0      38
2026-08-07   unknown     unknown    5             0          0        2      2       the ccea3027 squash (two months of work landed at once)
2026-08-14   unknown     unknown    3             0          0        0      10
2026-08-21   2           759        2             210        499      0      64      worktree closure phase 0.3; worktree closure complete;
                                                                                        gates-enforcing fix (db808bdf); graveyard seeded
```

*(The 2026-08-21 row's milestone cell is reflowed across two lines above
for readability — the tool itself truncates that cell to 60 characters and
prints one line; re-run the regeneration command to see the raw truncated
form. Every number in this table is verbatim from the tool's own output;
only that one cell's text is lightly reflowed.)*

**Anchors** — the only three points where `live-local`/`unpushed` are known,
not `unknown`:

| date | provenance | unpushed | local | remote | stashes | source |
|---|---|---|---|---|---|---|
| 2026-08-27 | CITED | 746 | 63 | 150+ | 70 | `docs/superpowers/plans/2026-08-27-branch-equilibrium.md`, Evidence basis line — the original cleanup finding, before this session touched anything |
| 2026-08-27 | CITED | 754 | 2 | 157 (mirror) | 0 | `.superpowers/sdd/2026-08-27-branch-equilibrium/progress.md`, Task 1's live TRUNK line — mid-session, after the local-branch/stash cleanup but before Tasks 1–2 landed |
| 2026-08-27 | MEASURED | 759 | 2 | 157 (mirror) | 0 | this run, via `scripts/crew/brief/trunk_health.py` — the same instrument the TRUNK line uses |

Read plainly: **all three anchors fall on the same day.** That is not this
document rounding — it is the honest shape of the evidence. The 63→2
local-branch drop and the 70→0 stash drop happened *within* 2026-08-27,
between the first and second row. This analyzer cannot place that drop on
an hour, because the branches that vanished left no graveyard record and no
surviving reflog (see "What the data cannot show," first bullet). The
746→754→759 unpushed climb across the same three points is real and in the
opposite direction — normal commit traffic during a session outweighing
the branch cleanup's own unrelated effect on that count.

---

## What the data cannot show (read this before the verdicts)

- **Which of the 61 local branches died today, when each was created, or
  how long each sat unclaimed.** Deleting a branch deletes its reflog with
  it. The two anchors above prove the *count* dropped 63→2 within one day;
  nothing in this repository can now say which 61 branches, or attribute a
  lifespan to any single one of them.
- **The graveyard's 210 branch-death records are not 210 independent data
  points in time.** Every one shares `deleted_on = 2026-08-25` and a reason
  starting `seeded:` (verified by reading the file — `graveyard_summary()`
  in the analyzer flags this automatically, `all_records_seeded: true`).
  That date is when the record was *written* — a retroactive bulk log of
  the 2026-08-24 worktree-fleet closure and custodian archive — not a
  distinct death timestamp for each branch. The curve above reports this
  honestly: all 210 land in one week, because that is genuinely when they
  were recorded, and it does not pretend to spread them across the weeks
  they probably actually died in.
- **Remote-branch "first seen" undercounts true branch creation.** A branch
  pushed, worked, and deleted from `dev-origin` before this checkout ever
  fetched it leaves no reflog trace at all — it is invisible to every row
  in the table above. The `rem-1st-seen` column is a floor, not a census.
- **Two separate reflog horizons, both starting 2026-05-20.** This
  checkout's own HEAD reflog reaches back to `2026-05-20T19:02:10-05:00`;
  the earliest remote-branch reflog entry is `2026-05-20T17:00:59-05:00`.
  Anything before that — including the first seven weeks after the
  advisory rule below was written — is a blind spot this analyzer states
  rather than fills.
- **The custodian's automatic consolidation-hold log survives only for its
  final ~48 hours, not its whole life.** `runtime/logs/server_stderr.log`
  is truncated on every server relaunch, so most of the audit's five-week
  serving window (2026-07-22 onward) is unrecorded — what survives is
  Aug 25–27, and it happens to be dispositive for the question that
  matters (see intervention 3, below: it proves the audit fired, held, and
  was never actually enforced). Do not read "a log survives for the final
  48 hours" as "no evidence exists" (an earlier draft of this document
  said exactly that, and a reviewer's disk search falsified it) — but do
  not assume the earlier weeks looked the same either; they are genuinely
  unknown, not assumed identical to the window that survived.

---

## The interventions, dated, verdict from the data

Every date below is resolved live by the analyzer (`git show -s
--format=%cI <sha>`), not hardcoded prose — see `MILESTONES` in
`scripts/forge/sprawl_history.py`.

### 1. Advisory rules — `CLAUDE.md`'s branch-awareness section (2026-03-31, `a2f50b48`)

The rule ("before creating ANY new file or feature, check for existing work
on other branches") is a text instruction with no enforcement behind it —
nothing checks whether it was read, let alone followed.

**Verdict: did not move the number, as far as the data can see.** The rule
predates this repository's reflog horizon by seven weeks — that window is
genuinely unknown, not zero. But every week the data *can* see after it —
2026-05-20 onward, fourteen-plus weeks with the rule already in place —
still shows ongoing branch creation (0 to 39 remote-branches-first-seen per
week, no visible drop correlated to the rule's age). A text rule with
nothing checking it did not change behavior in the window this analyzer can
observe.

### 2. The janitor — `scripts/forge/tidy_refs.py` (2026-06-17, `3da17fcb`)

Ships dry-run by default; `--apply` is required to actually reap anything.
No call site in the current tree invokes it automatically — it is, and
appears to have always been, a manual CLI tool someone has to remember to
run with the dangerous flag.

**Verdict: did not move the number, structurally.** A report-only tool that
nobody is required to act on cannot reduce a count by itself, and the data
agrees: the weeks immediately following its landing (2026-06-19 onward)
show some of the highest creation activity in the whole series (38 in the
week of 2026-06-26, 39 in the week of 2026-07-31). Whether it was ever run
with `--apply` is not recorded anywhere this analyzer can read; its design
alone is sufficient to explain the non-effect.

### 3. The custodian — `thomas/forge/branch_custodian.py` (2026-07-22, `ca020741`), made automatic same day (`d173a5b1`)

This is the one pre-cleanup mechanism that did not depend on anyone
remembering to invoke it: a server-side loop
(`thomas/server/consolidation_maintenance.py`, wired into server startup at
`thomas/server/app_routes_init.py:456-458`), every six hours by default,
placing a "consolidation hold" once branch count crosses a ceiling
(`DEFAULT_BRANCH_CEILING = 10`), lifted once it drops back.

**Verdict: ran, detected correctly, held for two straight days — and
blocked nothing, because the one function that could have blocked
anything was never called by anything.** This is proven, not inferred, on
two independent legs (both re-verifiable with the commands below):

**It fired.** `runtime/logs/server_stderr.log` (this checkout's live
server, boot 2026-08-25T20:27:36, v0.19.26) records the audit firing every
~6 hours — `consolidation hold placed: 63 branches over a ceiling of 10`
at 20:28:19, 02:28:26, 08:28:32, 14:28:39, 20:28:45, 02:28:52, 08:28:59 —
eight audits across ~42 hours, then `consolidation hold released` at
14:28:59 on 2026-08-27, only after the manual cleanup dropped the count.
`git merge-base --is-ancestor d173a5b1 495fcc27` confirms the serving
build (the 0.19.25 bump) contained the loop; the run store
(`runtime/.thomas/runs.sqlite3`) shows the server actually served 0.19.24
(2026-07-22→25), 0.19.25 (2026-07-27→08-15), and 0.19.26 (from 08-25) — the
loop was present in the serving build across that span, with
**2026-08-15→25 genuinely unrecorded** (no run-store activity either way —
not claimed as evidence the loop ran or didn't in that window). This
softens an earlier draft's "live for five full weeks" to what the evidence
actually carries: in the serving build for five weeks, demonstrably firing
in the ~48 hours the log covers, unknown in between.

**It could not have blocked anything, in any window.** `guard_new_branch`
— the *only* function in this codebase able to refuse a branch on an
active hold — has **zero call sites** anywhere in the tree, and never had
one in this repository's history:

```
git grep -n guard_new_branch $(git rev-parse HEAD) -- '*.py'
# -> matches only the module's own definition and its own test
git log --all --oneline -S guard_new_branch -- . ':!tests' ':!runtime'
# -> no commit, ever, added a production caller
```

This also directly refutes the "ceiling set too high to trigger"
hypothesis: the ceiling is 10, and the log above shows real triggers at
63.

This is this program's own documented **finished-code-with-no-caller**
shape, found here inside its own detection-and-consolidation mechanism: a
correct detector, wired to an enforcement function that genuinely works
when called directly (`tests/test_consolidation_hold.py::
test_hold_actually_blocks_a_new_branch` proves the function itself is
sound), that nothing in production ever calls. The CLI compounded this: it
used to print "Consolidation hold PLACED -- new branches are blocked until
this clears" whenever a hold was placed — nothing was blocked, ever. Fixed
in this same fix round (see the CHANGELOG): both `Hold.message()` and the
CLI's hold-placed line now say plainly that the hold is recorded, not
enforced at branch creation, and name `branch_claim_gate.py` as what
actually enforces.

**Why Task 2's `branch_claim_gate.py` is designed not to repeat this shape
— and where that design currently stands.** The custodian's hold is
*voluntary*: something has to remember to call `guard_new_branch` at the
exact moment a branch is created, and for this mechanism's entire life,
nothing ever has. `branch_claim_gate.py`'s destination is the pre-push
hook path instead — git itself invokes every configured pre-push hook on
every push, unconditionally unless the pusher passes `--no-verify` (a
bypass this repo's own commit tooling never uses, but a human `git push`
on the command line still can), with no opt-in step for the branch being
pushed. That is the structural argument for *why* a hook is the right
place to stand, and it holds regardless of wiring state.

**But at HEAD, the gate is not yet configured in any local
`.pre-commit-config.yaml` hook.** The only place it currently runs is
CI's `branch-claim-gate` job — RED_PATH-covered, fires on every PR opened
against `dev`/`main`, not in `gates-required`'s `needs:`, so a red X
rather than a stop, and it never fires at all on a bare `git push` to a
feature branch, since no workflow triggers on that event. That means
today's shipped state has exactly the shape this document just convicted
the custodian for: a correct mechanism with a caller reachable from only
one of the two places that matter. What keeps this from being the same
failure is that the missing half is a **named, written tap item**
(`PRAXIS-PHASE14-BREAKGLASS/batch.md` section (k)) awaiting one Windows
Hello sign-in, not an indefinite, undiscovered silence the way
`guard_new_branch`'s zero call sites were. See
`plans/thomas/tasks/PRAXIS-BRANCH-EQUILIBRIUM/status.md` for the exact,
current enforcement state — this document states the destination the
design is built toward, not a claim that it has already arrived.

### 4. The squash — `ccea3027` (2026-08-12)

"land two months of work — gateway auth, dead code, and instruments that
can see it." A one-time landing of accumulated changes into a single
commit.

**Verdict: bought temporary debt relief, did not change the equilibrium.**
A squash collapses *existing* unmerged work; it does nothing to whatever
let branches keep forming afterward, because it is not a standing
mechanism at all. The data confirms this directly: the two weeks after the
squash (2026-08-14, 2026-08-21) still show new branch and worktree-archive
activity, and the local branch count still reached 63 fifteen days later.

### 5. The gates-not-enforcing window, closing at `db808bdf` (2026-08-25T08:56:44)

Before this fix, the monolith guard — and by extension confidence in the
rest of the pre-commit gate battery on this machine — scanned the wrong
tree, silently. This is a second, independent instance of the disease
intervention 3 proved directly above: a mechanism can be built, wired, and
even fire correctly, and still enforce nothing, because nothing downstream
actually trusts or calls it. (These are two distinct defects, not one
causing the other — the custodian's `guard_new_branch` has zero callers
regardless of whether pre-commit gates are trustworthy; they are named
together here for the shared shape, not because fixing one would have
fixed the other.) A hold, a gate, a rule — none of them mean much if the
thing that is supposed to enforce it is quietly not doing so, or is never
asked to.

**Verdict: too recent to show a trend of its own; it is the precondition
for every mechanism after it to mean what it claims.** This fix landed two
days before this document. Its test is not in this curve — it is whether
Task 1's TRUNK line and Task 2's `branch_claim_gate.py` (both built and
verified *after* this fix, on top of a gate layer now confirmed live) hold
over the coming weeks. See "Going forward," below.

### 6. This cleanup (2026-08-27) — 63→2 local branches, 70→0 stashes

**Verdict: the only intervention in this dataset that visibly, immediately
moved the number.** Both counts are anchored on real, cited measurements on
the same day (see "The curve," above). This is real progress, stated
plainly — but it is a one-time manual sweep, the same shape as the squash
and the 2026-08-24 worktree-fleet closure (59 archived+removed, 7 skipped,
0 bytes lost — `0c4b46ed`/`d12571cd`) before it. Nothing about a sweep, by
itself, prevents the count from climbing right back — that is what Tasks 1
and 2 exist to do differently: make the trunk's state loud every session
(so nobody has to remember to look) and make forking cost a recorded,
expiring claim (so nobody has to remember to clean up).

---

## Going forward: the instrument this proof sets up

Every prior mechanism above either had no enforcement behind it (the
advisory rule, the janitor) or ran inside an enforcement layer later found
to be silently non-functional (the custodian, until `db808bdf`). Tasks 1
and 2 of this plan are built and tested *after* that fix, specifically to
not repeat that shape:

- **`scripts/crew/brief/trunk_health.py`** (Task 1): prints one `TRUNK:`
  line every session — unpushed count, local/remote branch counts, stash
  count, and the last pre-push gate battery's result with its age — always
  a live read or an honestly-aged cache, never a guess, never silent. The
  push-gate field itself reads `unchecked` until its cache-writer is wired
  (a named tap item, `PRAXIS-PHASE14-BREAKGLASS/batch.md` section (j)) —
  the line already says so honestly rather than reporting a fabricated
  `ok`.
- **`scripts/forge/branch_claims.py` + `scripts/forge/gates/branch_claim_gate.py`
  + `scripts/forge/branch_sweep.py`** (Task 2): the design is that a branch
  pushed to any remote needs a recorded claim (owner, purpose, expiry ≤60
  days) or the push fails, naming the remedy, and that an expired or
  unclaimed local branch is archived-then-deleted after a 7-day grace,
  never silently. **At HEAD that design is built and CI-verified, not yet
  locally armed**: `branch_claim_gate.py` fails an unclaimed branch's PR
  today (CI-visible, non-required — see `status.md`), but no local
  pre-push hook calls it, so a plain `git push` on this machine still
  succeeds silently; `branch_sweep.py` is tested and correct but dry-run
  by default and scheduled nowhere, so an expired claim is not actually
  swept until a human runs `--apply`. Both gaps are named, single
  tap/decision items — see `status.md` for exactly what closes each one.

**The one-month flatness criterion.** Thirty days from this cleanup
(2026-09-26), re-run `python scripts/forge/sprawl_history.py --json` and
check its `anchors` list's newest "measured, this run" entry:
`local_branches` should still read in the single digits, `stashes` should
still read near zero, and no new bulk `"seeded:"` write should have hit
`docs/ops/graveyard.json` in the interim (that shape — a sudden bulk
recording after silence — is exactly what this document found evidence of
once already, at the 2026-08-24/25 worktree closure). Flat, boring, single
digits: the mechanism held — but before crediting it, check that it was
ever armed: if the tap items (the local pre-push hook, the cache writer)
were never signed and the sweep never scheduled, a flat curve credits the
quiet month, not the mechanism, and the verdict is "untested", not "held".

**The red condition.** If a future run of this same analyzer shows local
branches climbing back into double digits, or shows another mass
graveyard-seed event, that is not noise to explain away — it means the
model this plan is built on (landing must stay cheap and loud; forking must
become a recorded, expiring claim) was wrong, or was never armed at all
(the taps unsigned, the sweep unscheduled — check that first: it is the
cheapest explanation and the likeliest), or was defeated the
same way the custodian's automatic hold provably was: built, wired, firing
correctly, and never actually stopping anything because the one function
that could stop something was never called by anything. That is not a
hypothesis here — `runtime/logs/server_stderr.log` and a static
zero-caller check (`git log --all -S guard_new_branch`) both confirm it
happened at least once already, in this repository's own history
(intervention 3, above). Treat a repeat of that exact shape — a mechanism
that runs and logs correctly but that nothing downstream ever calls or
trusts — as the diagnosis to check first, before building a fifth
mechanism on top of a program that has already failed to enforce twice
this way.

This document does not itself close the incident this plan opened in
Task 1 — that closure, and the live TRUNK line quoted at the moment of
closing, belong to Task 4.
