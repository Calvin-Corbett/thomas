# Branch equilibrium: closure under the loop's law

Plan: `docs/superpowers/plans/2026-08-27-branch-equilibrium.md`.
Ledger: `.superpowers/sdd/2026-08-27-branch-equilibrium/progress.md` (authoritative
what-happened record; `task-{1,2,3,4}-report.md` carry full detail per task).
Companion doc: `plans/thomas/tasks/PRAXIS-BRANCH-EQUILIBRIUM/proof.md` (the
sprawl curve, the one-month flatness criterion, the red condition — referenced
below, not duplicated).

Verified against the tree at the commits this task lands, not copied from any
prior report.

---

## What enforces where, today

**`scripts/crew/brief/trunk_health.py`** (Task 1). Wired into every session
start. Live read every time — unpushed count, local/remote branch counts,
stash count. The push-gate battery field reads a cache file nothing writes
yet (every candidate writer call site — `merge_readiness.py`, `preflight.py`,
`dead_ref_gate.py`, `scripts/_gate_python.py`, `.pre-commit-config.yaml`
itself — is protected under `agent_safety.toml`). Until that one-line wiring
lands, this field reads honestly as `unchecked (never)`, never a fabricated
`ok` — see the tap item below.

**`scripts/forge/branch_claims.py` + `docs/ops/branch_claims.json`** (Task 2,
seeded this task). The registry is no longer empty — it holds **8 records**
(not 10; `dev`/`main` are exempt, not registry entries — see below).

`dev` and `main` need no claim at all, and never appear in this file: the
gate's own hardcoded rule exempts them
(`_EXEMPT_BRANCHES = frozenset({"dev", "main"})` in
`scripts/forge/gates/branch_claim_gate.py`, verified by reading the gate's
source directly, not assumed from the plan's prose). Stated here first
because it explains why the count below is 8, not 10.

The registry's 8 records:

- `integration/unify-2026-08-14` — the one held local branch, owner
  `calvin (standing delegation 2026-08-24, claude-recorded)`, purpose
  awaiting an archive-push before deletion, expires `2026-09-30`.
- Seven codex remote-branch names, one per distinct commit-content cluster
  found by cross-referencing every `codex/*` remote branch's tip sha against
  the head shas recorded in `plans/thomas/tasks/PRAXIS-PHASE0-WORKTREES/
  closure_report.md`'s salvage log (`git rev-parse` on each `codex/*` ref,
  compared byte-for-byte against every `head=<sha>` in that report — not a
  name-based guess). **This task's brief named six; the cross-reference
  independently found seven** — stated plainly rather than forced to fit.
  Each cluster's representative claim names the duplicate branch names that
  share its exact commit content (several `codex/*` names are byte-identical
  pushes of the same work under different names — a real finding, not a
  seeding artifact). All seven: same owner form, purpose "held for
  unlanded-work inspection per the cleanup," expiry `2026-09-30`. Full list,
  ids (branch names, this registry's natural key — see
  `branch_claims.py`'s own docstring, "No `id` field: a claim is looked up
  by branch name directly"):
  - `codex/dead-legacy-phase-c-3a884c61`
  - `codex/release-preflight-repair-20260723`
  - `codex/dead-legacy-retirement-20260723`
  - `codex/installer-hardening-candidate-2c84f452`
  - `codex/unified-permissions-artifact-579b3c98-20260723`
  - `codex/organic-routing-no-regex-20260722`
  - `codex/release-history-20260723`

The ~150 grandfathered pre-existing remote branches are **deliberately not
seeded**. `branch_claim_gate.py` only gates ref CREATION (see its own
GRANDFATHERING section) — an unseeded pre-existing branch is exactly as
pushable, updatable, and deletable as a seeded one, so seeding it changes
nothing the gate enforces. That population is the cleanup's own stage-3
deletion plan's job, not this registry's.

**What the 2026-09-30 expiry actually does, per branch class — traced
live via `branch_sweep.plan_sweep(today=...)`, not assumed:**

| date | `integration/unify-2026-08-14` (local) | the 7 `codex/*` claims (remote) |
|---|---|---|
| 2026-09-30 | `live_claim`, kept | live |
| 2026-10-01 | `expired_claim`, **delete=True** | expired |

Neither consequence is automatic. For the local branch, `delete=True` only
materializes the moment a human runs `python scripts/forge/branch_sweep.py
--apply` — nothing does that on a schedule (stated above: not scheduled
anywhere), so on 2026-10-01 itself, nothing happens by itself. For the
seven remote holds, expiry is **entirely inert either way**:
`branch_sweep.py` only ever examines local branches, and
`branch_claim_gate.py` only ever inspects ref *creation* — these seven refs
were created long before this registry existed, so the gate has nothing
left to check against them regardless of claim state. Their expiry is a
bookkeeping event only, not an enforcement one.

**The real hazard, and the ordering it depends on.**
`integration/unify-2026-08-14`'s recorded purpose is "awaiting an
archive-push before deletion" — the plan is to push it to a remote archive
location, then let it be swept. If a human runs `--apply` *after*
2026-10-01 but *before* that archive-push has actually happened, the sweep
archives it only to `refs/archive/branch/...` — a **local-only** ref on
this one machine — and then deletes the working branch, with the push its
own purpose names never having occurred. The honest minimum this document
commits to: the archive-push is a precondition on this branch's deletion,
and the only place that records this intention is the claim's own
`purpose` field — no workboard task or batch step queues the archive-push
itself, so whoever schedules the sweep must land the archive-push first.
The ordering holds today only because the sweep is unscheduled (see
above), by circumstance, not by a code-level guard or a queued task. No guard was added in this task;
if `branch_sweep.py` is ever wired to a schedule (the follow-up decision
above), the archive-push for this specific branch must land first, or the
scheduling change itself must special-case it — named here so whoever
makes that follow-up decision does not rediscover this the hard way.

**Not to be confused with 2026-12-01.** `2026-09-30` (this section) is
when the seeded branch claims lapse. A different date,
`2026-12-01` — the day all three of this repo's `accepted-risk` records
(9 + 1 + 1 incidents, per `PRAXIS-PHASE2-BATCH1/status.md`'s "designed
convergence" section) pass their own, unrelated `expires_on` of
`2026-11-30` (valid through that day; expired the morning after) and
`REOPEN DUE` fires for all of them at once — belongs to a completely
different registry (`accepted_risks.py`, not `branch_claims.py`) and a
different closure mechanism (`problem_closure_gate.py`'s `accepted-risk:`
form, not the gate covering this incident). Relative to this plan's own
flatness re-run (`2026-09-26`, `proof.md`): the claim lapse is four days
after it, the risk convergence nine weeks after; the two alarms are
unrelated to each other; no document before this one states that
plainly, so this line exists to stop the two alarms from blurring
together later.

**`scripts/forge/gates/branch_claim_gate.py`** (Task 2). RED_PATH-registered
(`tests/test_every_enforcing_gate_can_fail.py`'s `RED_PATH_CASES`, key
`branch_claim_gate.py` — confirmed present by direct grep, not assumed) and
wired into `.github/workflows/gates.yml` as the `branch-claim-gate` job. That
job runs on **every** PR today and genuinely enforces: a present-but-empty
registry is a real "nobody holds a claim" answer, not infrastructure
absence — this is `branch_claims.py`'s own documented contract, not a
loophole. Before this task, the registry was empty and the job showed a red
X on every branch. After seeding, the seven codex branches and the one local
branch above pass; any other non-exempt branch pushed today still shows red,
correctly.

**What "enforcing in CI" does NOT yet mean: required.** `branch-claim-gate`
is deliberately **not** in `gates-required`'s `needs:` list — flipping that
is a real policy change (every contributor's branch must carry a live claim
before it can land), not a mechanical one-line edit this task makes
silently. **Claims seeded: yes (this task).** The required-flip itself is
queued as its **own follow-up**, with its own reviewer sign-off, exactly the
way Task 2's report named it — not claimed here, not silently taken.

**`scripts/forge/branch_sweep.py`** (Task 2). Exists, tested (registry CRUD,
7-day grace, archive-then-delete, fail-closed on an unreadable registry).
**Dry-run by default. Not scheduled anywhere** — no cron, no server-side
maintenance loop, no CLI wrapper calls it automatically. Running it on a
cadence is a **follow-up decision**, not something this task claims is
already happening. This is a deliberate, disclosed gap, not an oversight:
the janitor (`scripts/forge/tidy_refs.py`) shared this exact shape
(dry-run-by-default, nobody required to run `--apply`) and `proof.md`
convicts it for exactly that reason — shipping `branch_sweep.py` already
wired into a schedule, without review, would risk repeating the shape this
whole program exists to stop, not avoid it.

---

## The live TRUNK line, quoted fresh

Run immediately before this document was written
(`python scripts/crew/brief/trunk_health.py`):

```
TRUNK: 764 unpushed | branches 2/157(mirror) | stashes 0 | push-gate unchecked (never)
```

`push-gate unchecked (never)` is the honest state until the cache-writer tap
item below lands — not a bug this document is hiding.

---

## The one-month flatness criterion and the red condition

Both are defined in `plans/thomas/tasks/PRAXIS-BRANCH-EQUILIBRIUM/proof.md`
("Going forward: the instrument this proof sets up") — referenced here, not
duplicated, so the two documents cannot drift apart on the same claim.
Summary only: thirty days from the 2026-08-27 cleanup (2026-09-26), re-run
`python scripts/forge/sprawl_history.py --json` and check local branches
stay single-digit, stashes stay near zero, and no new bulk graveyard-seed
event occurs. The red condition: if sprawl regrows under enforcement, that
is not noise — it means the model this plan is built on was either wrong,
or was defeated the same way `branch_custodian.py`'s automatic hold
provably was (built, wired, firing correctly, and never actually stopping
anything because the one function that could stop something was never
called by anything — `proof.md`, intervention 3). Check that exact shape
first before building a fifth mechanism.

---

## Tap items, consolidated

Two tap items exist from this program, both one-line-or-shorter edits to
files `agent_safety.toml`/`.pre-commit-config.yaml`/pre-push-hook-chain
protects:

1. **`trunk_health.write_push_gate_cache()` wiring** (Task 1). One import
   plus one call, inside `merge_readiness.run()` after
   `evaluate_merge_readiness()` returns — the exact text is already in
   `trunk_health.py`'s own module docstring, quoted verbatim there so this
   document does not risk drifting from the shipped code:
   ```python
   from scripts.crew.brief.trunk_health import write_push_gate_cache
   write_push_gate_cache(
       ROOT, ok=ok, blocked_gates=[r["name"] for r in results if not r["ok"]]
   )
   ```
   `merge_readiness.py` is itself in `agent_safety.toml`'s protected list.

2. **`branch_claim_gate.py`'s pre-commit hook wiring** (Task 2). A new
   `.pre-commit-config.yaml` hook entry, `stages: [pre-push]`, styled
   identically to the sibling gate it mirrors in shape
   (`thomas-dead-ref-gate`):
   ```yaml
   - id: thomas-branch-claim-gate
     name: Thomas Branch Claim Gate (anonymous pushes need an owner)
     entry: python scripts/_gate_python.py scripts/forge/gates/branch_claim_gate.py
     language: system
     pass_filenames: false
     stages: [pre-push]
   ```
   Plus the matching promotion pair every prior gate promotion in this
   program has used: an `agent_safety.toml`
   `[protected].enforcement_scripts` entry for
   `scripts/forge/gates/branch_claim_gate.py`, and a
   `scripts/forge/gates/enforcement_manifest.json` re-bless
   (`enforcement_integrity.py --generate-manifest`, run last, after every
   edit — the manifest-last rule `PRAXIS-PHASE14-BREAKGLASS/batch.md`'s own
   fix wave already established).

**Chosen home: `plans/thomas/tasks/PRAXIS-PHASE14-BREAKGLASS/batch.md`, a
new clearly-marked amended section — not `PRAXIS-REF-EXACTNESS-BREAKGLASS`
and not a new file.** Checked both existing candidates before choosing:

- `PRAXIS-PHASE1-BREAKGLASS/batch.md` — the structurally closest precedent
  (it wired `dead_ref_gate.py`'s own pre-push hook, the gate
  `branch_claim_gate.py` most directly mirrors) — is **STATUS: EXECUTED**
  (landed `28518073`, 2026-08-25). A closed batch is not a place to append
  new, unrelated tap items; it is a historical record now.
- `PRAXIS-REF-EXACTNESS-BREAKGLASS/batch.md` is **STATUS: PREPARED** but
  covers a structurally unrelated defect class (DWIM-exact ref resolution
  in two pinned gates, `release_update_gate.py` and
  `worktree_branch_guard.py`) — wrong topic, would misfile these two items
  next to work that has nothing to do with branch claims or push-gate
  caching.
- `PRAXIS-PHASE14-BREAKGLASS/batch.md` is **STATUS: PREPARED** and is
  already the program's standing, repeatedly-amended home for exactly this
  shape of tap item — "promote an unpinned, CI-enforcing gate into local
  pre-commit/`commit.py` enforcement, one Windows Hello tap, nothing
  executes until it's signed." It already carries a Phase 1.4 section, a
  Phase 1.5 section, a Phase 2 section, and a Round 2 section, each added
  the same way this task adds its own — a clearly-marked new section,
  `STATUS: PREPARED` at the top left untouched, nothing in the file
  executed by adding text to it. This task amends that file with a new
  section (see the amendment below) rather than opening a fifth breakglass
  document for a two-item tap.

---

## The two carried-forward nits (T3 review)

Both fixed in this task, in passing, per the instruction carried from Task
3's review:

- **`proof.md`'s "unconditionally" gloss.** The intervention-3 prose said
  git invokes every pre-push hook "unconditionally, with no opt-in step" —
  true for the branch being pushed, but silent on `--no-verify`, which lets
  a human bypass pre-push hooks entirely on the command line. One clause
  added: "unconditionally *unless the pusher passes `--no-verify`* (a
  bypass this repo's own commit tooling never uses, but a human `git push`
  on the command line still can)."
- **`consolidation_hold.py`'s present-tense docstring.** "why Task 2's gate
  stops sprawl" claimed a settled outcome about a mechanism whose one-month
  flatness window has not run yet. Changed to "why Task 2's gate is built
  to stop sprawl" — one word, in the code file, landed as part of this
  task's commit (not a docs-only fix wave; `consolidation_hold.py` is
  Python, counted toward this commit's wrapper limit).

---

## What this task did not do, stated plainly

- Did not flip `branch-claim-gate` into `gates-required`'s `needs:` list.
  Queued as its own follow-up with its own reviewer sign-off, per the
  brief's explicit instruction, not silently taken as part of closure.
- Did not wire either tap item's actual file edits (both touch
  `agent_safety.toml`/`.pre-commit-config.yaml`, both protected). Prepared
  as a batch-doc amendment for the owner's tap, same discipline as every
  prior protected-file change in this program.
- Did not schedule `branch_sweep.py` anywhere. It is tested and correct,
  not automatic. Running it on a cadence (cron, a server maintenance loop
  like the custodian's — with `guard_new_branch`'s zero-caller lesson from
  `proof.md` explicitly in mind before wiring anything automatic near
  branch creation again) is a follow-up decision for you to make, not
  something this task assumes on your behalf.
- Did not seed claims for the ~150 grandfathered remote branches. Explained
  above; the gate's own creation-only design makes this a no-op for
  enforcement either way.
