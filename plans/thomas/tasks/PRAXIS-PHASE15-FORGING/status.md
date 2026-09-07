# Phase 1.5 status: the forging loop closes

Spec: `docs/superpowers/specs/2026-08-24-praxis-first-design.md` §1.5
Plan: `docs/superpowers/plans/2026-08-25-forging-loop.md`
All three tasks landed on `dev`:
- Task 1 (accepted-risks registry): `e6731922`
- Task 2 (the closure gate + 3 fix rounds): `a399edff`, `cf8454af`, `09bdc7f0`, `bff8a29e`
- Task 3 (router split, template, surfacing + 1 fix round): `0f76d4ce`, `19ee8de2`, `7eac7b7d`, `6e478804`
- Task 4 (this doc + the batch amendment): `0eb5fa56`
- Final-review fix wave (Critical-1 — expiry must re-open a resolved
  incident; surfacing is the re-open channel): `389cb12b`

This revision of the document was corrected against the final-review
findings — the earlier version asserted the strong form of "expiry
re-opens" as already-implemented fact before `389cb12b` landed. See "What
enforces where" below for the corrected, verified mechanism.

Verified against the tree, not copied from the plan or the reviews.

---

## The loop's shape

Before this phase, nothing stopped a `plans/thomas/WORKBOARD.md` Task
Problems entry or a `PROBLEM.md` header from flipping to `status=resolved`
with nothing behind it — no landed fix, no tombstone, no sign-off. That
"resolved" read as done forever, because closure was never re-checked.

`scripts/forge/gates/problem_closure_gate.py` now refuses that transition
unless the record carries exactly one `closure:` line that RESOLVES, in one
of three forms:

- `closure: gate:<filename>` — `<filename>` must be a key of
  `RED_PATH_CASES` in `tests/test_every_enforcing_gate_can_fail.py`: a
  landed gate the enforcing-gate ratchet has proven still fails on a real
  violation. Naming an unwatched gate (on disk, not red-path-covered) FAILS,
  naming the file.
- `closure: tombstone:<id>` — `<id>` must resolve in the graveyard
  (`docs/ops/graveyard.json` via `scripts/forge/graveyard.py`'s `load()`), a
  record of a deliberate removal.
- `closure: accepted-risk:<id>` — `<id>` must resolve in the accepted-risks
  registry (`docs/ops/accepted_risks.json` via `scripts/forge/accepted_risks.py`'s
  `load().get()`) AND be unexpired at the moment THIS resolving transition is
  evaluated. An id that resolves but has already EXPIRED FAILS the gate,
  naming the owner and the expiry date — the resolution itself is refused,
  so the incident cannot land as `resolved` on a lapsed acceptance in the
  first place. This blocks a resolution in flight, evaluated once, in a
  diff; it is not a standing watch over a resolution that already landed —
  see "Session start" below for the mechanism that actually re-checks a past
  resolution as time passes.

Zero closure lines on a resolving incident is a FAIL (closure is the whole
point). More than one is also a FAIL, naming the ambiguity — an incident has
exactly one terminus, never two competing explanations for how it ended.

**The record-level vs. file-level boundary is the phase's central ruling.**
A whole registry file that fails to parse at all (`graveyard.load` /
`accepted_risks.load` raising `SystemExit` on a malformed — not missing —
file, or the `RED_PATH_CASES` import failing outright) is treated as
file-level infrastructure absence: the affected incident is classified
`unavailable`, which is a PASS with a printed note, never a FAIL. The
registry being broken is not evidence that the closure itself is bad, and an
operator's missing flag or a transient import failure must never expire or
block real work.

A single RECORD that loads fine but carries a garbage value — an
`accepted-risk:<id>` whose `expires_on` is not a real date, reachable only
by hand-editing the registry (normal writes via `accepted_risks.record_risk`
validate the date before it can ever land) — is the opposite case: a
POSITIVE DEFECT IN THAT RECORD, always a FAIL naming the record id and the
parse defect, never a note-pass. Treating a garbage date as merely
unavailable would turn a hand-edited malformed `expires_on` into an
immortal-risk evasion channel: a risk that can never expire because it can
never be checked. (This exact gap went through two fix rounds — the first
guard caught only `ValueError`; a present-but-non-string `expires_on`
`null`/int/bool/etc. raised `TypeError` straight through instead. The final
guard at `bff8a29e` catches both, verified against every hand-edit-reachable
shape: `null`, int, bool, list, dict, float, empty string, and a
well-formed-but-impossible date.)

## What enforces where

**CI, now.** `problem_closure_gate.py` is wired into
`.github/workflows/gates.yml`'s diff-range job (`--base "$BASE_SHA" --head
"$HEAD_SHA"`) and registered in `tests/test_every_enforcing_gate_can_fail.py`'s
`RED_PATH_CASES` under key `"problem_closure_gate.py"` — the enforcing-gate
ratchet demands every registered gate demonstrably fail on a real violation,
and this one does (a fixture-forced resolved transition with no `closure:`
line).

**Locally, only after the tap.** The gate is not yet in `agent_safety.toml`'s
`enforcement_scripts`, not integrity-checked by
`scripts/forge/gates/enforcement_manifest.json`, and not run by
`scripts/crew/brief/commit.py`'s `LOCAL_GATE_COMMANDS` or by any
`.pre-commit-config.yaml` hook. Confirmed by reading the tree directly:
`agent_safety.toml` has zero matches for `problem_closure_gate.py`, the
manifest has zero matches, and `commit.py`'s `LOCAL_GATE_COMMANDS` tuple has
zero matches. CI is the only place it runs today. The promotion is prepared,
not executed — see
`plans/thomas/tasks/PRAXIS-PHASE14-BREAKGLASS/batch.md`'s "Phase 1.5
additions" section for the one-tap plan that closes this gap alongside the
already-prepared `workboard_evidence_gate.py` promotion from phase 1.4.

**Capture-side.** `scripts/crew/tasks/plans.py`'s `_build_problem_template`
now stamps every newly-created `PROBLEM.md` with a `## Closure` section
stating the three forms as a fenced (non-triggering) example, so the
vocabulary is taught at creation time, before an incident ever needs it. A
mutation-verified test binds the template directly to the gate's own parser
(`problem_closure_gate._closure_lines`), not to a hand-copied expectation.

**Session start.** `scripts/crew/brief/incident_surfacing.py` prints two
lines every run, honest zero included in both.

`INCIDENTS: N open without closure` (plus the oldest three) covers incidents
that have never yet resolved. It is resolution-aware by construction, not by
convention: it imports the gate's own `_evaluate_incident` (not a second
copy of the resolution logic), so a dangling closure reference, an EXPIRED
accepted-risk, or an unresolvable `gate:`/`tombstone:` id on a NOT-yet-
resolved incident all count as open — the same verdict the gate itself would
reach, because it is the same function.

`REOPEN DUE: N resolved incidents whose closure no longer holds` is the
actual expiry watcher, and it exists because of a gap the gate cannot close
by itself. The gate's own scoping is diff-based, and correctly so for what a
diff can see: it evaluates a resolution once, at the moment that resolution
is proposed, and (by design) skips a standing resolved incident whose
closure line hasn't changed since — re-litigating an unchanged resolved line
on every unrelated commit would just duplicate whatever originally validated
it. The consequence, found in final review and reproduced: neither of the
gate's own `is_expired` call sites can ever see an incident that is already
closed, so an accepted risk that lapses AFTER its incident resolved was
indistinguishable from one that never lapsed at all — closure was asserted
as self-maintaining when nothing was actually watching it. Fixed at
`389cb12b`: surfacing now evaluates every incident's closure line through
that same shared function regardless of status, resolved included. A
resolved incident whose closure still resolves stays invisible (the common
case, no noise). One whose closure no longer resolves — expired, dangling,
or an unrecognized form — lands in `REOPEN DUE`, a distinct line from
`INCIDENTS`, never merged into the open count: a stale past resolution is a
different fact from a newly discovered open incident. A resolved incident
with NO closure line at all — the disclosed legacy-drain population, closed
before this gate existed — is deliberately excluded from `REOPEN DUE`;
counting it would misrepresent "never checked" as "checked and failing."

**No status flip happens automatically anywhere in this loop.** Landing in
`REOPEN DUE` is a printed line at session start, not a write to the
workboard or the `PROBLEM.md` file — an agent or you has to act on it (land
a fix, record a fresh accepted risk, or otherwise touch the incident) before
the tracked record itself changes. "Expiry re-opens the incident" describes
what the surfaced line tells the reader to do next, not something the
software does to the file unattended.

## The router's monolith debt

`scripts/crew/brief/startup_router.py` was 1142 lines, over the soft cap
and unbaselined — touching it at all would trip the monolith gate. Rather
than add to the debt, Task 3 paid it first: a move-only split extracted a
coherent module (`scripts/crew/brief/startup_signals.py`, 628 lines) from
the router (now 624 lines), verified AST-identical name-for-name against the
pre-split file (16 moved names byte-identical — `ROOT`/`_REPO_ROOT` are
module-bootstrap lines present in both files, not moved, so they don't count
here; 20 of 21 kept names byte-identical, one differing by a single added
blank line). The incident
surfacing wiring landed as a separate commit on top of the already-green
split. Both files are under the 800-line soft cap.

## Follow-ups (stated, not hidden)

- **Legacy `PROBLEM.md` files drain passively, not retroactively.** The
  closure gate only fires on a resolving transition it sees in a diff — it
  does not, and was never designed to, sweep every existing `PROBLEM.md` in
  the repo and force it through resolution. A legacy file with dangling
  Failure Records and no closure line stays exactly as it is until someone
  touches it (moves it to `status=resolved`, or edits its closure line on a
  standing resolved). This is a stated limitation, not a claim of
  retroactive enforcement.
- **`audit-24h-backstop` is the known first customer.** Read directly:
  `plans/thomas/problems/audit-24h-backstop/PROBLEM.md` carries **40**
  Failure Record entries (`grep -c "^### "`) in the live working tree, status
  `up_for_grabs`, and no `closure:` line. (The committed `HEAD` copy has
  **38** — that file was already dirty, with unrelated pending edits, before
  this phase began; do not expect this exact number to hold, re-run the
  count for the current figure, same caveat as the `INCIDENTS` number
  below.) It is one of the incidents `incident_surfacing.py` currently
  counts as open.
- **A known, accepted evasion in the off-board path.** `problem_closure_gate.py`'s
  `_header_status` takes the FIRST status-looking line in a `PROBLEM.md`; a
  deliberately self-contradictory file (a decoy `- status: open` placed
  above the real `- Status: resolved`) can mask resolution on the file-only
  scope path (no matching WORKBOARD Task Problems entry). This requires
  intentionally malformed content, only bites incidents off the tracked
  board, and the pinned `workboard_task_problems` gate forces every tracked
  task onto the board anyway — evasion-by-intent only, the same trust model
  every text-format gate in this repo accepts, documented in the gate's own
  docstring but not previously stated here.
- **CHANGELOG catch-up.** GUARDRAILS Rule 6 requires a `CHANGELOG.md` entry
  per logical unit of work; none of this phase's original 10 commits
  (`e6731922..0eb5fa56`) added one, and `changelog_gate.py`'s 3-code-file
  threshold never fired because every commit touched at most 2 files under
  `thomas/`/`scripts/`/`extensions/` — `tests/`, `docs/`, and `plans/` don't
  count toward it. That is itself a phase-1.5-shaped incident (a rule that
  cannot see its own violation) and would be its own first customer for this
  same closure vocabulary. A single catch-up entry covering the whole phase
  was added to `CHANGELOG.md` in the final-review fix wave rather than
  backdated per commit.
- **The real live numbers, at time of writing:**

  ```
  .venv/Scripts/python.exe scripts/crew/brief/incident_surfacing.py
  ```

  prints:

  ```
  INCIDENTS: 25 open without closure
  ...
  REOPEN DUE: 0 resolved incidents whose closure no longer holds
  ```

  (Both counts read the live working tree, which carries more problem
  directories than the last committed snapshot — do not expect these exact
  numbers to hold; re-run the command for the current figures. `REOPEN DUE`
  reading zero today is expected: `docs/ops/accepted_risks.json` is still
  empty, so there is no accepted risk yet that could have lapsed.)
- **The promotion tap is not yet signed.** Everything under "what enforces
  where" above that says "locally, after the tap" stays CI-only until you
  run the batch in
  `plans/thomas/tasks/PRAXIS-PHASE14-BREAKGLASS/batch.md`. Nothing in this
  phase executes that tap for you.

---

If you are the one who eventually signs the tap: it is one Windows Hello
pass that promotes two gates at once — the phase-1.4 evidence gate and this
phase's closure gate — into the same local enforcement your other commits
already go through. Until then, both gates catch violations only on CI, not
on your own machine before you push.
