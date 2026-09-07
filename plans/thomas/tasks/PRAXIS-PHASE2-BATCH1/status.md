# Phase 2, batch 1 status: the ledger tells the truth it enforces

Spec: `docs/superpowers/specs/2026-08-24-praxis-first-design.md` §2
Plan: `docs/superpowers/plans/2026-08-25-phase2-repairs-batch1.md`
Ledger: `.superpowers/sdd/2026-08-25-phase2-repairs-batch1/progress.md`
(authoritative what-happened record; task-{1,2,3,4}-report.md and
task-{1,2,3,4}-review.md carry full detail per task).

Verified against the tree at commit `1e7b99a5` (HEAD when this document was
written), not copied from the plan or the reviews. Every commit sha, line
count, and surfacing line below was checked directly against the repo, not
assumed from a prior report.

**Amended** after a final whole-branch review
(`.superpowers/sdd/2026-08-25-phase2-repairs-batch1/final-review.md`) found
one undisclosed operational gap in this document (the revocation path's tap
collision), one defect this batch itself produced (CHANGELOG
cross-contamination with concurrent sessions), and one missing CHANGELOG
entry. All three are addressed below, in place, rather than as a separate
document — a closure doc that needs its own erratum is still the closure
doc.

---

## What landed, with evidence

### Task 1 — the ledger stops lying (recurring vocabulary + landed-scope closures)

`087ff50e` (recurring vocabulary + the accepted risk record + 9 closures +
the `ELECTRON-BUMP-RECURRING` marker) + `9fe0b289` (fix round: the
`PROBLEM.md` glob was depth-1-only and missed any task_id containing a
literal `/`; changed to a recursive glob, verified against the real
three-directory-deep record it had been missing).

- `incident_surfacing.py` gained a `RECURRING: N standing` line: a
  `PROBLEM.md` header line `- Recurring: <cadence>` excludes the record from
  the open-without-closure count without hiding its existence. The closure
  gate itself needed no change — a test proves a recurring-header-only edit
  never trips it.
- Nine `THOMAS-GITHUB-ISSUE*/PROBLEM.md` records, whose scope had landed in
  `ea788bac` (2026-08-14) with no closure practice yet to close them, were
  set to `status: resolved` with `- closure: accepted-risk:<id>` (the id is
  below). `ELECTRON-BUMP-RECURRING` got its recurring marker; it stays
  `up_for_grabs` — standing work, not a scar.
- **Structural finding, verified by both implementer and reviewer:** all 10
  touched `PROBLEM.md` files live under `plans/thomas/problems/`, which
  `.gitignore:90` denies by default (a deliberate control dating to a
  2026-05-19 private-content leak through that directory) except for a named
  allowlist these 10 files are not on. They are real, on disk, correctly
  read by `incident_surfacing.py` (a plain filesystem walk, no git) — but
  they can never appear in a git diff, so `problem_closure_gate.py`'s
  diff-range CI check passes on this commit by finding nothing to check
  (`0 changed PROBLEM.md file(s)`), not by verifying the 9 closures. This is
  the batch's biggest structural finding; see the owner-decision queue below.
- An over-match residual was found and ruled honest, not a misreport: a
  stray `PROBLEM.md` copy under a task subdirectory (e.g. an `archive/` or
  `notes/` folder reusing the same task_id marker) is counted as its own
  open record by the any-depth glob. Every row still states a real file's
  real header status and real path — nothing fabricated, nothing hidden.
  The error direction is strictly toward surfacing (over-counting,
  traceable by path), never toward concealment, which is the direction this
  program treats as dangerous. Zero live instances exist today (every
  top-level problems directory holds exactly one `PROBLEM.md`); this is
  carried forward as a known, disclosed shape rather than a defect.

### Task 2 — salvage debris dies with death records

`449cf5dc` (deletes `thomas/server/app_part03.py`, adds
`tests/test_salvage_debris_stays_dead.py`, CHANGELOG) + `dbf5dfb3` (the
`PRAXIS-PHASE14-BREAKGLASS/batch.md` amendment adding step 6a) +
`323cf1c8` (fix round: a byte-exact recovery block for the graveyard append,
and an owner-text reword).

Four proven orphans — `thomas/server/app_part03.py` (its loader only
activates when all four `app_part0N.py` exist; only one did) and three
`apps/site/src/app/globals_part0N.css` files (duplicating the still-full
`globals.css`) — were each verified fresh at HEAD immediately before
deletion, not assumed from recon. `docs/ops/graveyard.json` is protected
under `agent_safety.toml`'s `enforcement_files`, so the landing was
honestly split rather than routed around: **only** `app_part03.py`'s
deletion, its test, and the CHANGELOG entry are committed. The three CSS
deletions and the four-record graveyard append are on disk, verified
correct, and pending — see "Pending under expiring skips" below. This
split is stated in the commit and this document, not buried.

Monolith guard: the plan assumed a `23 -> 21` delta (2 conceptual orphan
groups); the guard actually counts one violation line per file, so the real
delta once all four orphans are committed is `23 -> 19`, not `23 -> 21` —
confirmed on disk (`monolith_guard.py` currently reports **19** violations,
re-run fresh for this document). At the currently *committed* HEAD, where
only `app_part03.py`'s deletion has landed, a fresh checkout's guard
reports 22.

### Task 3 — the verification gaps close

`21b38b4a` (fallback ref resolution + a real `task_id` column on
`run_store`) + `da5836f5` (CI's absent run-store documented, not silently
skipped) + `f7a523f0` (fix round: fallback refs fully qualified).

- **Commit-kind verification** now resolves its target through an ordered
  fallback (`dev`, `origin/dev`, `dev-origin/dev`) instead of a bare `"dev"`
  string, so a PR checkout with only `origin/dev` verifies instead of
  skipping. The review reproduced a real spoofing hazard in the first
  version — an unqualified fallback name let a local branch literally named
  `dev-origin/dev` (git allows slashes; a real second remote of that name
  exists on this repo) silently shadow the intended ref, verifying a forged
  commit and failing a legitimate one. Fixed by fully qualifying every
  fallback entry (`refs/heads/dev`, `refs/remotes/origin/dev`,
  `refs/remotes/dev-origin/dev`), closing the shadowing case. One narrower
  residual remains — see "Known debts carried."
- **Run-kind binding** gained a real `task_id` column on `run_store`
  (additive migration, verified safe against a pre-migration DB). No
  current caller has a task_id in scope, so both real callers pass the
  honest default `None` — the capability lands ahead of any consumer,
  which is disclosed rather than faked with a synthetic caller.
- **CI's run-store absence** is now a documented, named `UNAVAILABLE`
  rather than a silently-skipped flag: the run-store DB lives outside the
  repo, per-machine, and can never exist in a CI checkout, so wiring a
  throwaway CI DB would have flipped honest `UNAVAILABLE` passes into false
  `FAIL`s on unrelated production run ids.

### Task 4 — the self-review endpoint stops looking dead

`997b6c42` (cache-with-TTL, single-flight background refresh) +
`1e7b99a5` (fix round: exceptions outside the caught tuple now stamp and
surface; `stale` now reflects the served report's own age, not the last
attempt's).

`GET /api/self-review` previously ran its 15-30s LLM generation inline on
the request path — any caller with an ordinary timeout saw it as down. The
fix serves a cached, `generated_at`-stamped report immediately and
refreshes in the background, single-flighted (verified under a 480-request
concurrency fuzz: never more than one generation in flight per cache key).
The review found and the fix round closed two real gaps: an exception
outside the originally-caught tuple left the retry clock unstamped, so a
broken generator relaunched on every single request while every caller
kept seeing a permanently healthy `"generating"`; and a failed refresh
reused the same clock the `stale` flag was computed from, so an
arbitrarily old report could be served as `stale: false` with no error
visible. Both are fixed: the background task now catches broadly, logs,
stamps, and re-raises; and the cache tracks two separate clocks — attempt
recency (throttles retries) and served-result recency (drives `stale`) —
with a `refresh_error` field surfaced whenever the most recent attempt
failed.

---

## CHANGELOG cross-contamination — a defect this batch produced, caught by final review

Three of this batch's own commits published `CHANGELOG.md` entries for code
that had not landed yet, and one of this batch's own entries landed inside a
commit that was not this batch's. `CHANGELOG.md` is a single shared file,
and each of this batch's scoped commits staged it whole — while other
sessions were live in the same checkout, each commit picked up whatever the
file held at that moment, not only the section it was itself landing.

- `21b38b4a` (Task 3) carried two desktop sections — "Added (desktop — the
  agent can see a page by name, and act on it by name)" and "Fixed
  (desktop — three reasons a click could land nowhere)" — describing code
  that landed later, as `b3b35b7b` and `dceed73a`.
- `323cf1c8` (Task 2's fix round) carried "Added (browser shell — Thomas
  gets browser chrome)", 22 lines describing `browser_shell.js` /
  `browser_shell_panel.js` / `browser_shell.css`, which landed later at
  `6ad89055`.
- In the other direction: `da5836f5`'s own entry — "Fixed (gates — CI's
  absent run-store is named, not silently skipped)" — was not committed by
  `da5836f5` at all. It landed inside `b3b35b7b`, a foreign desktop-feature
  commit two commits later (`git log -S "CI's absent run-store is named,
  not silently skipped" --oneline -- CHANGELOG.md` → `b3b35b7b`). HEAD's
  CHANGELOG carries this entry correctly and exactly once
  (find it by its heading, "CI's absent run-store is named, not silently
  skipped" — a line-number citation here rots as the file grows, and the
  first version of this paragraph proved it by drifting 26 lines in one
  commit) — the content is accurate and present, only
  mis-attributed to a different commit than the one whose message describes
  it. Because the entry genuinely exists at HEAD, no catch-up entry was
  needed for `da5836f5` itself.

Net effect at HEAD is benign: every section above appears exactly once,
nothing is missing, and nothing describes code that still doesn't exist.
The defect is that for a window of commits, the repository's own public
changelog described code that was not yet in the tree, and three commit
messages do not fully match what actually landed in them — a live instance
of the exact "a document states something false about its own result"
family this phase exists to eliminate, produced by this batch rather than
caught by it. History is not rewritten to fix this; this disclosure is the
fix.

**Standing hazard, named for whoever writes batch 2's plan:** a live
concurrent-session checkout will keep producing this shape as long as a
scoped commit stages `CHANGELOG.md` wholesale. A future practice candidate
— named here, not built — is per-commit changelog staging discipline: an
explicit hunk-scoped `git add -p CHANGELOG.md`, or writing the entry
immediately before the commit that lands it, whenever another session is
known to be live in the same checkout.

**The one genuinely missing entry:** `dbf5dfb3` (the `batch.md` step-6a
amendment) had no CHANGELOG entry anywhere at HEAD — its substance survived
only inside `449cf5dc`'s prose. This is a real gap against the plan's own
explicit Global Constraint ("CHANGELOG entry per commit ... write the entry
anyway"), caught by final review. A catch-up entry for it was added to
`CHANGELOG.md` in this fix wave, self-disclosing its lateness rather than
being backdated — the same precedent as the phase-1.5 closure's own
catch-up entry (`plans/thomas/tasks/PRAXIS-PHASE15-FORGING/status.md`,
"CHANGELOG catch-up").

---

## The accepted risk

```
id:         2026-08-25-nine-task-records-scope-landed-in-ea788bac-2026-08-14-without-closure-no-practice-yet-auto-closes-landed-scope-records-1
owner:      calvin (standing delegation 2026-08-24, claude-recorded)
reason:     nine task records' scope landed in ea788bac 2026-08-14 without
            closure; no practice yet auto-closes landed-scope records
reviewed_on: 2026-08-25
expires_on: 2026-11-30
refs:       .superpowers/sdd/2026-08-25-phase2-recon/recon.md#section-4-1
```

It covers exactly the 9 `THOMAS-GITHUB-ISSUE*/PROBLEM.md` records closed
under Task 1 — nothing else resolves against this id.

**How you revoke it, verified against the actual code
(`scripts/forge/accepted_risks.py`), not assumed:** the registry is
genuinely append-only by design — `record_risk` only ever appends, and the
module's own docstring states records are never edited or removed once
written, mirroring the graveyard's tombstone pattern. There is **no delete
or revoke command anywhere in this module** — the CLI (`python
scripts/forge/accepted_risks.py ...`) exposes only `record` and `list`, and
no other function in the file removes a record. So the plan's shorthand
("delete the record via the registry") does not correspond to any real
operation this tool provides.

The real revocation path, if you want to veto this before it expires on its
own on 2026-11-30, is a direct hand-edit of `docs/ops/accepted_risks.json`
— outside the module's supported API, the same way any plain JSON file can
be edited. Two ways to do it, both landing in the same place:

1. **Edit this record's `expires_on` to a past date.** This is the closer
   analog to a real veto: the record and its reasoning stay on the ledger
   (nothing about who accepted what or why is lost), only its validity
   lapses immediately instead of on 2026-11-30.
2. **Delete the record's JSON object from the `records` array entirely.**
   This also works — the id then resolves to nothing — but erases the
   acceptance's own history from the registry, which is a stronger action
   than a veto typically needs.

**This is only true before the tap.** `plans/thomas/tasks/
PRAXIS-PHASE14-BREAKGLASS/batch.md` section (h) — prepared, not yet run —
adds `docs/ops/accepted_risks.json` to `agent_safety.toml`'s
`[protected].enforcement_files`, for the identical reason
`docs/ops/graveyard.json` is already on that list: a gate trusts it as a
resolution authority, so it must not be silently editable. This is the same
tap "Pending under expiring skips" item 2 below sends you to for the
graveyard append — one tap, two files. Once it runs, `protected_files_gate.py`
covers this file too, and per this batch's own `449cf5dc`, that gate's local
staged mode has no agent-usable override, only a native Windows sign-in. So:
**before the tap, either hand-edit above is a plain, unprotected file edit.
After the tap, it is not** — you first run `python scripts/
breakglass_window.py on`, make the edit inside that time-boxed window, then
`python scripts/breakglass_window.py off`, the same ceremony as any other
protected-file edit.

Either edit has the identical downstream effect through the mechanism
already built for this: `problem_closure_gate.py`'s shared resolver no
longer finds a valid, unexpired `accepted-risk:<id>` for any of the 9
`PROBLEM.md` records' closure lines, so the next run of `incident_surfacing.py`
(which evaluates every incident's closure through that same shared
function, resolved status included) routes all 9 back into `REOPEN DUE`,
naming the dangling or expired reference. Nothing flips automatically in
the files themselves — `REOPEN DUE` is a printed line at session start, an
instruction to act, not a write to any file — but the resurfacing itself
requires no code change and no restart, only the hand-edit and the next
`incident_surfacing.py` run. Note also (from Task 1's own finding): this
whole mechanism is machine-local, because the 9 `PROBLEM.md` files
themselves are gitignored — a fresh clone never carries the records, so a
veto only matters on a checkout that has them.

---

## Pending under expiring skips (hard-fail 2026-10-01)

Both items are genuinely on disk, verified correct, and blocked by
something outside this batch's scope to fix:

1. **The three `apps/site/src/app/globals_part0N.css` deletions.** Blocked
   by `scripts/forge/gates/site_visual_proof.py`'s pre-existing footer-focus
   pixel-diff drift (~59.5% vs a 2% threshold), reproduced independently by
   both Task 2's implementer and its reviewer on a tree with the deletions
   entirely absent — proving the drift is broken baseline, not caused by
   this batch. Captured today as its own incident record (dogfooding the
   closure vocabulary this batch built): `plans/thomas/problems/
   site-visual-proof-baseline-drift-2026-08-26/PROBLEM.md`. That directory
   is untracked, for the same `.gitignore:90` deny-by-default reason as
   Task 1's 9 records — it exists on disk and is visible to
   `incident_surfacing.py`, but cannot be committed until the allowlist
   question below is resolved.
2. **The `docs/ops/graveyard.json` four-record append** (the death records
   for `app_part03.py` and the three CSS files). Blocked by
   `docs/ops/graveyard.json` being a protected file
   (`agent_safety.toml`'s `enforcement_files`); it rides the owner
   breakglass tap already prepared at `plans/thomas/tasks/
   PRAXIS-PHASE14-BREAKGLASS/batch.md` step 6a, which now also carries a
   byte-verified recovery block (a fenced JSON copy of the four records
   plus an idempotent append one-liner) in case this checkout's uncommitted
   state is ever lost before the tap runs.

`tests/test_salvage_debris_stays_dead.py` enforces both deadlines directly:
today it skips, naming the exact blocker; from 2026-10-01 it hard-fails
instead, so neither gap can rot silently past its date.

---

## Dormant until your next server restart

- **Task 3's run `task_id` column and binding** (`thomas/marketplace/
  observability/run_store.py`, `thomas/server/routes/chat_v2_run_store.py`).
  The migration is additive and safe against an already-running server's
  DB, but the new binding path only takes effect once the live process
  restarts and picks up the changed code.
- **Task 4's self-review cache, TTL, and single-flight behavior**
  (`thomas/server/routes/self_review.py`, the eager cache registration in
  `thomas/server/app_core.py`). Neither round of this task was ever
  verified against the live :8899 process, per the plan's constraint —
  only against the unit-test harness.

Neither was restarted or checked against :8899 at any point in this batch.

---

## Owner-decision queue

These were deliberately left untouched by this batch (stated in the plan's
own header) — restating them here so they are not lost:

- **The `praxis-unbypassable` E1 deferral ruling** (recon #2).
- **The `hardening-2026-06-12` phantom close** (recon #3).
- **`audit-24h-backstop`'s assign/retire decision** (recon #9) — it remains
  one of the incidents `incident_surfacing.py` counts as open today (see
  the live lines below).
- **Re-baseline-vs-split for the remaining non-orphan monolith
  violations** (recon #4). The plan's own header names this "the 21
  non-orphan monolith violations" — Task 2's investigation found the real
  count is lower once corrected for how the guard actually counts (one
  violation line per file, not per conceptual orphan group): 19 on disk
  today (all four salvage orphans already deleted from the filesystem),
  22 at the currently committed HEAD (only `app_part03.py`'s deletion has
  landed; the three CSS files are still tracked at HEAD pending their own
  blocker above). Whichever number is current when you look, it is an
  engineering decision — split each file or record a deliberate baseline
  waiver — that this batch did not make.
- **The `.gitignore` allowlist question.** This is the batch's single
  biggest structural finding, and it is two sentences: `plans/thomas/
  problems/*` is denied by default and only a named allowlist of
  directories is re-included (a deliberate control after a 2026-05-19
  privacy leak through that same directory), which means every
  `PROBLEM.md` this batch touched or created — the 9 closed records and
  today's new `site-visual-proof-baseline-drift-2026-08-26` incident —
  is invisible to git and to the closure gate's diff-based CI check, real
  and enforced only by `incident_surfacing.py`'s direct filesystem reads on
  whichever machine happens to hold the files. Extending the allowlist
  would make closure gate CI-verifiable for these records, but it trades
  against the privacy control the deny-by-default rule exists for — that
  tradeoff is yours to make, not this batch's.

---

## Known debts carried

- **`scripts/crew/workboard/claim_evidence.py` is at 799 of its 800-line
  unbaselined soft limit** (verified fresh: `wc -l` reports 799 today). The
  very next edit to this file — including the item below — will trip the
  monolith guard and needs either a module split or a deliberate baseline
  entry planned *before* that edit lands, not during it.
- **A residual "nested-DWIM" ref-resolution gap in Task 3's fix**, ruled
  Minor and non-blocking: `git rev-parse --verify` still DWIM-resolves a
  maliciously-created `refs/heads/refs/heads/dev` when the real
  `refs/heads/dev` is absent. The review's ruling: this grants zero
  capability beyond what the qualified-ref model already concedes (an
  actor able to create that nested ref could equally create the real one),
  so it is deliberately not fixed now. The stated hardening for the next
  touch of that file: probe existence with `git show-ref --verify <ref>`
  (exact path, no DWIM ever) before peeling with `rev-parse`.
- **Task 1's over-match disclosure sentence** — already stated above under
  Task 1's own section, repeated here because the review explicitly
  flagged it as something this document should carry: a stray `PROBLEM.md`
  copy under a task subdirectory counts as its own open record under the
  any-depth glob. The error direction is strictly surfacing, never
  concealment.
- **Task 4's 300-second cache TTL is a judgment call, not an evidenced
  number.** It balances "a `generating` status resolves within a couple of
  polls" against "not every request repays a 15-30s LLM call"; the recon
  did not specify a figure. Easy to retune
  (`_REFRESH_TTL_SECONDS` in `self_review.py`) if a different cadence is
  wanted.

**Final review's five Minors — disposition, not silently dropped.** None of
them are fixable in this document, the CHANGELOG, or the plan doc (the only
scope this fix wave owns), so each is disclosed here rather than actioned:
M-1 (the graveyard-append deadline test passes rather than skips on this
machine, because the working-tree graveyard already holds all four records
— the 2026-10-01 hard-fail only bites where the records are absent, i.e.
CI; a filesystem-state fact, not a documentation fix) is carried as-is.
M-2 (`997b6c42`, `1e7b99a5`, `91dff11b` carry subject lines with no body,
unlike this batch's other commits) and M-4 (`323cf1c8`'s message quotes the
owner's name as removed evidence) both describe already-landed commit
messages — no history rewrite, per this batch's own standing rule. M-3 (the
accepted-risk record's `refs` field points at a gitignored, machine-local
recon path) would require editing a live registry record to fix, which is
outside a docs-only fix wave and was already ruled acceptable-permanent for
the identical class of finding in `323cf1c8`'s own M3. M-5 (a
`Co-Authored-By` trailer present on one commit, `c172de95`, of twelve) is
cosmetic commit-history inconsistency, not a documentation defect.

---

## The spec's exit criterion

Spec §2's stated exit criterion is a month of organic use without a new
instance of the misreporting family this phase exists to catch — a working
instrument that reads as broken, or a claim that states something false
about its own result. **This batch starts that clock; it does not finish
it.** Every fix above landed under an adversarial review that reproduced
its own attacks by running code, not by reading it, and every open item
above (the two expiring skips, the owner-decision queue, the two dormant
server changes) is named rather than hidden — but "a month organic without
a new family instance" is a claim about what happens after this document,
not something this batch can assert about itself.

---

## Live surfacing lines, quoted fresh

Run immediately before this document was finalized, at HEAD `1e7b99a5`
plus the untracked `site-visual-proof-baseline-drift-2026-08-26` record
created by this task:

```
$ .venv/Scripts/python.exe scripts/crew/brief/incident_surfacing.py
INCIDENTS: 17 open without closure
  - agent-coordination-hardening-2026-05-28 (in_progress): plans/thomas/problems/agent-coordination-hardening-2026-05-28/PROBLEM.md
  - agent-messaging-reliability-2026-06-02 ((no status)): plans/thomas/problems/agent-messaging-reliability-2026-06-02/PROBLEM.md
  - audit-24h-backstop (up_for_grabs): plans/thomas/problems/audit-24h-backstop/PROBLEM.md
REOPEN DUE: 0 resolved incidents whose closure no longer holds
RECURRING: 1 standing
  - ELECTRON-BUMP-RECURRING: on every new Electron stable major -- standing work, not an open scar (recon #10)
```

The 16 this batch's Task 1 landed at (after its fix round) plus the one new
`site-visual-proof-baseline-drift-2026-08-26` incident this task created
equals the 17 shown above — the new record is the dogfood proof that a
freshly created incident, on this same untracked-directory footing as the
9 this batch closed, surfaces correctly under the vocabulary this batch
built.

---

## Batch 2 (2026-08-26)

Spec: `docs/superpowers/specs/2026-08-24-praxis-first-design.md` §2
Plan: `docs/superpowers/plans/2026-08-26-phase2-repairs-batch2.md`
Ledger: `.superpowers/sdd/2026-08-26-phase2-repairs-batch2/progress.md`
(authoritative what-happened record; task-{1,2}-report.md and
task-{1,2}-review.md carry full detail per task).

Every sha, line count, and surfacing line below was re-verified directly
against the tree at HEAD `f24cecd0` while writing this section, not copied
from a prior report.

**Subject-line correction:** the plan's own Task 3 step names this commit's
subject `docs(phase2): batch two lands - small, sharp, and the ledger is
fifteen`. That number was the plan's own expectation (17 recon baseline
minus 2 closures = 15) and it is wrong against what actually landed — the
real count is sixteen, for reasons in "The ledger now" below. This
document's commit uses the corrected subject: `docs(phase2): batch two
lands - small, sharp, and the ledger is sixteen honest lines`.

### What landed

**Task 1 — the split debt is paid, and the last ref trick dies**

`f7ce65f5` (move-only split: `claim_evidence.py` 799 -> 570 lines,
`claim_evidence_storage.py` created at 339 lines — both re-verified by
`wc -l` against the tree this section was written from) + `9ac14311` (the
sanctioned rider).

- The split moved 22 top-level names (`Evidence`, `parse_evidence`,
  `format_evidence_field`, the validators, `EvidenceRecord`,
  `record_evidence`, `read_evidence`, `strip_evidence`, the task-line
  helpers, and their supporting constants) into the new storage module,
  re-exported by assignment so `claim_evidence.X is
  claim_evidence_storage.X` holds for every one of them. Both the
  implementer's own AST/token comparison and the reviewer's independent
  re-run (a separate scratch script, not the implementer's) found the moved
  code token-identical to the pre-split blob, and the 22 names that stayed
  behind also token-identical modulo the one deliberate change below. All
  8 real call sites (5 test files, `reactivate.py`,
  `claim_evidence_sweep.py`, `workboard_evidence_gate.py` — the recon's
  7th candidate, `test_chatgpt_parity_proof_bundles.py`, turned out not to
  reference this module at all) needed zero edits.
- The one sanctioned rider: `_resolve_verify_target_branch`'s existence
  probe moved from `git rev-parse --verify <ref>^{commit}` to `git
  show-ref --verify <ref>`. The nested-DWIM trick this closes was
  reproduced by hand before the fix, not assumed — with the real
  `refs/heads/dev` absent, a locally created branch literally named
  `refs/heads/dev` (git allows slashes in branch names, so this is stored
  at `refs/heads/refs/heads/dev`) made `rev-parse --verify` resolve and
  pass an attacker's commit as if it were the real target branch, while
  `show-ref --verify` correctly refused it. Both new tests were proven
  live regression guards by re-running them against the pre-rider code
  (one failed, as it should). The reviewer's own adversarial fixture set
  (packed refs, a symref, a tag object at a ref path) found no residual
  gap in the fix.
- 126 passed, 1 xfailed (pre-existing, unrelated) across the full evidence
  + evidence-gate + reactivate/sweep suite set, confirmed independently by
  both implementer and reviewer. Verdict: **Approved**, 0 Critical / 0
  Important / 3 Informational.

**Task 2 — two incidents close because their problems are gone**

`e6ccd651` (the two new accepted-risk records + the registry CLI proof) +
`2e92ebfa` (the fix round: the closures themselves committed onto the two
tracked `PROBLEM.md` files).

- **runtime-protection-fix-2026-05-27** closed via
  `accepted-risk:2026-08-26-runtime-protection-fix-2026-05-27-...-1`. Fresh
  verification confirmed `thomas/tools/filesystem.py:252-266`
  always-protects the runtime flag/key paths ahead of the disable-flag
  bypass logic, and the 5-file protection test cluster ran 44/44 green.
  The honest finding underneath the closure: `RED_PATH_CASES`
  (`tests/test_every_enforcing_gate_can_fail.py:215-222`) names exactly
  six gates, and none of them — including `protected_files_gate.py`,
  the only plausible candidate, which guards a different class
  (commit-time protection of GUARDRAILS.md/AGENTS.md/architecture files),
  and which isn't registered either — covers filesystem-tool-level write
  protection. Rather than stretch a `gate:` closure onto a gate that does
  not actually watch this incident's class, this closed as an owned,
  dated, expiring risk instead — a refusal to misdescribe coverage that
  isn't there.
- **audit-24h-backstop** closed via
  `accepted-risk:2026-08-26-problem-record-py-s-unlocked-append-...-1`.
  The record is the ledger's oldest — this batch's plan named it
  explicitly as the record that stops accusing a healthy gate. Fresh
  verification: the Surface parity gate passes cleanly offline today
  (`Surface parity check: OK — server wire events: 13, web handlers: 25,
  cli EventType handlers: 8`, exit 0, `:8899` untouched — it's a pure
  static-content diff over three source surfaces). The 40 Failure Records
  on the file are not 40 live problems; most of them — 36 of the 40,
  measured by pairing timestamps within one second of each other — are
  the signature of two unlocked `auto_checks.py` processes racing within
  the same second, each calling `problem_record.py`'s unlocked
  read-modify-write append, during a since-fixed Surface-parity failure
  window. 4 records don't pair and aren't explained by this mechanism
  alone; the PROBLEM.md's own phrasing, "(almost) identical timestamps,"
  is the accurate one, and this section should not claim more precision
  than that. The real fix — a file lock
  in `problem_record.py` — cannot land in this batch because that file is
  pinned in `agent_safety.toml`'s protected-files list (confirmed at line
  144 of that file), so it closed as an owned, dated risk naming the
  double-fire mechanism, gated behind a future breakglass tap rather than
  fixed directly.
- These closed as **two separate accepted-risk records**, deliberately,
  because they are different diseases: A is a gap in the closure
  grammar's vocabulary (a fixed-and-permanently-tested incident that no
  gate watches has no closure form), B is a concrete concurrency defect in
  pinned code. Sharing one risk record would have misdescribed one of the
  two.
- Both records: owner `calvin (standing delegation 2026-08-24,
  claude-recorded)`, `reviewed_on: 2026-08-26`, `expires_on: 2026-11-30`
  — read directly from `docs/ops/accepted_risks.json` while writing this
  section, ids below.

### The milestone: the closure gate's first live resolving transition

The plan's original premise — that both `PROBLEM.md` files were
untracked and gitignored, so their closure edits could stay uncommitted —
was false, caught by the review: `git ls-files` lists both,
`git check-ignore -v` matches neither. Because closures on ungitignored,
tracked files are exactly the shape `problem_closure_gate.py`'s CI
diff-check watches for, the fix round committed them (`2e92ebfa`), and
that commit is the gate's first-ever encounter with a real resolving
diff, checked twice, in two different modes, by two different people:

- **Staged mode, pre-commit, by the implementer**, run by hand against the
  exact staged diff before `2e92ebfa` landed:
  `Problem closure gate: PASS -- every resolving incident in this diff
  names something that resolves.` (consulted 19 Task Problems entries, 2
  changed PROBLEM.md files, 2 resolving, resolved=2, unavailable=0).
- **Diff-range replay, post-commit, by the reviewer**, run independently
  against `2e92ebfa~1..2e92ebfa`:
  `PASS -- every resolving incident in this diff names something that
  resolves` (same counts: consulted 19, 2 changed, 2 resolving,
  resolved=2, unavailable=0, exit 0).

Both runs verified this section's own commands were re-derivable, not
just reported. Every prior `PROBLEM.md` closure in this program (batch 1's
9, and both of this batch's) has resolved through `incident_surfacing.py`'s
direct filesystem read; this is the first time the gate itself — the CI
mechanism meant to catch a false or absent closure at commit time — has
seen a real one and passed it correctly.

### The two new risks

Read directly from `docs/ops/accepted_risks.json` at HEAD:

```
id: 2026-08-26-runtime-protection-fix-2026-05-27-is-fixed-and-permanently-tested-thomas-tools-filesystem-py-252-266-always-protects-runtime-flag-rel-runtime-key-rel-44-44-protection-tests-green-but-no-red-path-cases-gate-covers-filesystem-tool-level-write-protection-of-the-runtime-protection-control-files-the-closure-grammar-has-no-form-for-a-fixed-and-permanently-tested-incident-that-a-gate-does-not-watch-1
expires_on: 2026-11-30
covers: runtime-protection-fix-2026-05-27's closure grammar gap — fixed
and permanently tested, watched by no RED_PATH gate.

id: 2026-08-26-problem-record-py-s-unlocked-append-can-double-fire-records-when-two-auto-checks-py-processes-run-within-the-same-second-the-40-audit-24h-backstop-failure-records-were-produced-this-way-during-a-since-fixed-surface-parity-failure-window-the-real-fix-is-a-file-lock-in-pinned-problem-record-py-gated-behind-a-future-tap-1
expires_on: 2026-11-30
covers: audit-24h-backstop's double-append mechanism in pinned
problem_record.py, real fix tap-gated.
```

Both share the same veto path already documented for batch 1's risk
record above (see "The accepted risk" section) — a direct hand-edit of
`docs/ops/accepted_risks.json` (either an `expires_on` rollback or
deleting the record object), which routes both incidents back into
`REOPEN DUE` on the next `incident_surfacing.py` run once
`problem_closure_gate._resolve_closure` can no longer find a valid,
unexpired match. No new mechanism was built for this; it's the same
shared resolver, exercised twice more.

### The ledger now

Fresh run, at HEAD `f24cecd0`, immediately before finalizing this section:

```
$ .venv/Scripts/python.exe scripts/crew/brief/incident_surfacing.py
INCIDENTS: 16 open without closure
  - agent-coordination-hardening-2026-05-28 (in_progress): plans/thomas/problems/agent-coordination-hardening-2026-05-28/PROBLEM.md
  - agent-messaging-reliability-2026-06-02 ((no status)): plans/thomas/problems/agent-messaging-reliability-2026-06-02/PROBLEM.md
  - bible-public-system-2026-05-22 (up_for_grabs): plans/thomas/problems/bible-public-system-2026-05-22/PROBLEM.md
REOPEN DUE: 0 resolved incidents whose closure no longer holds
RECURRING: 1 standing
  - ELECTRON-BUMP-RECURRING: on every new Electron stable major -- standing work, not an open scar (recon #10)
```

16, not the plan's expected 15. **Composition, corrected during Task 2's
own review after an initial misattribution:** 17 (batch-1's close,
which already included `wrapper-bypass-and-false-claim-2026-08-26` —
its own timestamp (04:41:09 local) predates the batch-2 recon's HEAD
commit `858c8c98` (04:49:42 local) by 8 minutes 33 seconds, so it was
already inside that 17, not a new arrival) minus 2
(this batch's two closures, both held, confirmed absent from the 16)
plus 1. **The +1 is `DESKTOP-CODE-SIGNING`** — a genuinely new incident,
filesystem-birth-timestamped 18 seconds after the batch-2 recon file was
written, opened by another concurrent session, untracked, `status:
up_for_grabs`.

**Flagging this prominently, because it will hit you, not this batch:**
Windows Smart App Control moved to enforcement on this machine and now
blocks the desktop shell's unsigned `electron.exe` outright — the app
ran and verified fine for hours before the policy flipped, no code
changed, the binary is simply unsigned. `run-ui.cmd` and the browser UI
are unaffected; only the packaged desktop app is blocked. The record is
explicit that disabling or bypassing Smart App Control is not an
engineering option here — that switch is effectively one-way on Windows
11 — and that the real fix is a packaged, code-signed build
(`electron-builder` plus a certificate). Signing a build is a
code-signing-account action, not something this loop can do on your
behalf: **it belongs in your queue below**, and it will surface again at
your next attempt to launch the packaged desktop app, not before.

### Owner queue GROWS by

- **`DESKTOP-CODE-SIGNING`** (above) — the desktop shell cannot launch as
  a packaged app until a code-signed `electron-builder` build exists; the
  certificate and signing step are yours to arrange.
- **The messaging status-field stamp decision**
  (`agent-messaging-reliability-2026-06-02`) — the mechanism its own
  success criteria ask for (unread-inbox surfacing at agent startup, a
  default unread view, sent-message receipts, a pre-commit block while
  mail is unread) is already built at HEAD. What's left is not
  engineering: only the record's own bookkeeping — whether and how to
  mark it closed — remains, and that's a decision about the closure
  vocabulary, not a missing feature.
- **The `test:` closure-form design question.**
  `runtime-protection-fix-2026-05-27`'s own record names itself the
  closure-grammar gap's **second** instance, and that ordering is the
  correct one — this document previously said "first" and left the
  sentence naming no subject at all; both are corrected here.
  Batch-1's landed-scope accepted-risk (`2026-08-25-nine-task-records-
  ...-1`, covering the 9 `THOMAS-GITHUB-ISSUE*` closures — full id under
  "The accepted risk" above) was the first time this program reached for
  an owned, expiring risk in place of a closure form the grammar doesn't
  have; `runtime-protection-fix-2026-05-27`
  (`2026-08-26-runtime-protection-fix-2026-05-27-...-1`, full id under
  "The two new risks" above) is the second. Neither this batch nor batch
  1 built a `test:` closure form — that would be a real design decision
  (what makes a test "permanent" enough to close an incident on its own,
  without a gate watching it forever) that this loop deliberately left
  unmade.

  **This is a designed convergence, not two isolated risks, and it is
  bigger than either batch's own section states on its own.** All three
  accepted-risk records this program has ever written share the
  identical `expires_on: 2026-11-30`: batch-1's landed-scope risk
  (`2026-08-25-nine-task-records-...-1`, covering **9** incidents) and
  this batch's two (`2026-08-26-runtime-protection-fix-2026-05-27-...-1`
  and `2026-08-26-problem-record-py-s-unlocked-append-...-1`, **1** each
  — full ids above and under "The two new risks"). That is **11
  incidents**, not 2, all due to reopen on the same day: on 2026-12-01,
  `REOPEN DUE` fires for all 11 at once unless the vocabulary and
  practice questions each risk stands in for — the landed-scope closure
  practice, the `test:` closure form above, and the
  `problem_record.py` file-lock tap below — are answered first. Left
  alone, `incident_surfacing.py`'s own `_reopen_reason` docstring calls
  its REOPEN DUE output "a three-line session-start note" by design; on
  2026-12-01 that compact intent breaks against reality — 11 incidents
  each get their own REOPEN DUE line, not this document's surprise to
  spring on you then, but named here as the design decisions' actual
  deadline. The long-id style is part of what that day will look like: a
  fresh `incident_surfacing.py` run simulated against 2026-12-01 (no repo
  mutation) renders the `audit-24h-backstop` REOPEN line at 388
  characters and the `runtime-protection-fix-2026-05-27` REOPEN line at
  479 — `_reopen_reason` interpolates the full accepted-risk id. The
  long-id style itself is not a correctness hazard elsewhere (a
  hard-wrapped closure line in a `PROBLEM.md` fails loudly, naming the
  truncated id, rather than silently resolving against the wrong thing) —
  but this specific rendering is a readability problem, not a safety one,
  and it's naming a follow-up candidate rather than fixing it here: a
  `[:60] + "…"` truncation in `_reopen_reason` would keep the resolver
  exact while keeping the session-start note actually readable on
  2026-12-01.
- **The `problem_record.py` file-lock tap candidate.** The real fix for
  the audit-24h-backstop double-append (a file lock around the
  read-modify-write in `record_failure`) cannot land until
  `problem_record.py` — pinned in `agent_safety.toml`'s protected-files
  list — is opened under a breakglass tap, the same ceremony batch 1's
  graveyard-append pending item already uses.

### Follow-ups: the sibling DWIM class

The show-ref rider fixed one instance of a name-based ancestry check that
a maliciously-named nested ref could DWIM-shadow. The reviewer's own scan,
independently confirmed while writing this section, found four more
call sites in the same class, all in trusted-context gates rather than
adversarial-evidence paths (materially lower exploitability, which is why
none of them were in scope for this batch):

- `scripts/forge/tidy_refs.py:126` — `git merge-base --is-ancestor name
  base`, `name` a ref string, not a resolved sha.
- `scripts/forge/gates/release_sync_gate.py:158` — a `merge-base` walk
  over the ref-name fallback list `("dev-origin/dev", "origin/dev",
  "dev", "origin/main", "main")`.
- `scripts/forge/gates/release_update_gate.py:198` — `git merge-base
  --is-ancestor commit ref` on a ref name.
- `scripts/forge/gates/worktree_branch_guard.py:166` — same pattern.

A sweep candidate, not scoped to any task yet.

### Debts cleared

- **`claim_evidence.py`'s 799/800 headroom problem is gone.** Split to
  570 + 339 lines, both well clear of the 800-line soft limit, verified
  by `wc -l` against the tree this section was written from.
- **The nested-DWIM residual named in batch 1's "Known debts carried" is
  dead.** `_ref_resolves` now probes with `git show-ref --verify` (exact
  path, no DWIM) end to end, and the rider's own tests were proven live
  regression guards, not vacuous, by failing against the pre-fix code.
