# Phase 1.4 status: what "done" actually proves today

Spec: `docs/superpowers/specs/2026-08-24-praxis-first-design.md` §1.4
Plan: `docs/superpowers/plans/2026-08-25-claims-that-verify.md`
All four tasks landed on `dev`: `fbd22be0..42343a30`, with a further
whole-branch review fix wave on top (blind-window gate scoping, the
merge-base rule exception, and the worker's refused-done branch). Verified
against the tree, not copied from the plan.

---

## What verifies today

**commit kind** (`commit:<sha>`) is `"verified"` iff BOTH hold:
1. the sha is an ancestor of `dev` (`git merge-base --is-ancestor <sha> dev`), AND
2. it is *bound* to the claiming task: either the `task_id` appears as a
   whole token in the commit's own message/trailers (`git log -1 --format=%B
   <sha>`), or an `evidence_not_before` timestamp was supplied and the
   commit's committer time is at or after it.

Not an ancestor at all -> `"failed"` regardless of binding. Landed but
unbound -> downgrades to `"attested"` (see below), never silently accepted
as proof.

**run kind** (`run:<run_id>:<from>-<to>`) is `"verified"` iff ALL hold:
1. an explicit `db_path` was supplied (this library never falls back to the
   live server database),
2. the run exists in that run_store db and is finalized ok,
3. every seq in the claimed `<from>-<to>` range is present in the run's
   NDJSON replay, AND
4. it is bound: `task_id` appears as a whole token in the run's own
   `session_id`/`profile`/`mode` text, or `not_before` <= the run's
   `started_at`.

No caller today stamps a claiming `task_id` into any run's metadata
(confirmed by reading `thomas/server/routes/chat_v2_run_store.py`'s
`start_chat_v2_run`), so as of this phase run-kind evidence can only reach
`"verified"` via the `not_before` path, never via name-binding, until a
caller is updated to stamp it.

Both bindings use a whole-token match (`_task_id_bound_in_text` in
`scripts/crew/workboard/claim_evidence.py`), not a substring check -- see
"notable catches" below for why that distinction is load-bearing in this
repo.

## What is attested-only (recorded, not independently proven)

- **gate kind** (`gate:<name>:<exit_code>`) is ALWAYS `"attested"`, never
  `"verified"` -- phase 1.4 records that a gate produced a result but does
  not re-run the gate to confirm it.
- **Unbound-but-landed evidence**: a commit that IS an ancestor of `dev`, or
  a run that IS finalized ok with its seq range present, but with no
  `task_id` match and no `not_before` given (or `not_before` given but the
  timestamp predates it) -- landing is necessary but was proven insufficient
  (see "first-commit-verifies" below). Reason text: `"landed on dev but not
  bound to this task - treat as claim, not proof"` (commit) / the run
  equivalent.
- **`not_before`-bound evidence, on re-check**: `claim_cleanup.py
  --evidence-sweep`'s re-verification call never has access to the original
  `not_before` (the task's claim/start time isn't persisted on the workboard
  line) -- it only re-tries the `task_id`-in-text binding. So evidence that
  reached `"verified"` at the done transition purely via `not_before` (which
  is the *only* way run-kind evidence verifies today, since nothing stamps
  `task_id` into run metadata) downgrades to `"attested"` on every later
  sweep pass. This is deliberate, not a bug -- the sweep must never punish
  evidence for losing a binding context it never stored -- but it does mean
  the sweep can only ever *re-confirm* "verified" via the name-binding path.

## What expires and what does not

**Expires** (`claim_cleanup.py --evidence-sweep`, driven by the existing
apply/release plumbing, the done->queued legal transition, moved to `## Up
For Grabs`, claiming agent messaged):
- a `status=done` task with NO `evidence=` field and NO recorded
  `evidence_recorded_at` timestamp at all -- the **legacy** case, predating
  evidence recording. Not gated by TTL; expires on the first sweep pass,
  tagged `"legacy done without evidence"`.
- a `status=done` task with missing evidence and a recorded
  `evidence_recorded_at` older than `--ttl-hours` (default 72).
- a `status=done` task whose stored evidence RE-VERIFIES `"failed"` for a
  REAL reason (see below) and whose recorded timestamp is older than TTL --
  including a commit sha that has since vanished from `dev`.

**Never expires**:
- `"verified"` evidence.
- `"attested"` evidence of any kind (gate kind, unbound-but-landed
  commit/run, or `not_before`-losing-context on re-check) -- attested is a
  real, checkable claim, just not proof bound to this cycle, and phase 1.4
  does not treat "not proof" as "expire it".
- evidence whose check infrastructure is unavailable: a `"failed"` verdict
  whose `reason_code` is in `claim_evidence.UNAVAILABLE_REASON_CODES`
  (`"db_path_required"` -- no `--run-store-db` given for a run-kind claim;
  `"git_unavailable"` -- `git` itself failed to run for a commit-kind claim).
  Both route to the sweep's `skipped` list, never `candidates`; infrastructure
  absence is never treated as proof the evidence is bad.
- a stored `evidence=` field that fails to parse at all -- also routed to
  `skipped`, flagged for human review, never silently expired.

## Evidence is per-cycle (reopening revokes)

`reactivate.set_task_status` calls `claim_evidence.strip_evidence` on every
transition whose FROM-status is `done` (`done -> queued`, `done ->
claimed`), removing `evidence=`/`evidence_recorded_at=` from the task's
Active Task line. This closes an attack a reviewer reproduced: a `done ->
queued -> claimed -> in_progress -> review` round trip used to leave the
ORIGINAL `evidence=` field untouched (only `status=` ever changed), so a
task could be hand-flipped straight back to `done` -- bypassing
`set_task_status` entirely, the same shape `workboard_evidence_gate.py`
exists to catch for `issue.py`'s parallel writer -- and the gate would still
see, and pass, the PRIOR cycle's evidence, even if it was genuinely verified
at the time. It proves nothing about the new cycle's work. Now a reopened
task starts every cycle with no evidence on its line at all, so a bypass
hand-flip is caught the ordinary way: as missing evidence.

## The worker auto-done behavior change

This is the phase's one behavior change to live tooling. `worker.py`'s
review -> done auto-transition (around line 399-425) no longer treats
pipeline exit 0 as done. It checks whether the pipeline itself moved `HEAD`
(landed a commit) between run start and end:

- **A commit landed**: auto-done fires with
  `evidence=commit:<sha>`, `evidence_not_before=<task_started_at>` -- the
  normal verified/attested path applies.
- **No commit landed**: the task is HELD, not silently marked done.
  Concretely: `held_count` increments; a loud line prints
  (`REVIEW HOLD <task_id>: pipeline succeeded but landed no commit - done
  requires evidence`); NO completed/approved message fires; the claim is
  **not released** (it stays visible on the board, in progress); a `p1`
  blocker message is sent to the task-manager agent asking it to review and
  land the missing commit or reassign. `held_count` folds into the loop's
  overall `ok` exactly like `failure_count` does.
- **A commit landed but the done transition was REFUSED** (whole-branch
  review fix wave -- e.g. the landed commit failed evidence verification):
  mirrors the held branch. `refused_count` increments (and
  `completion_count`, credited optimistically before this outcome was
  known, is decremented back out); a loud line prints (`DONE REFUSED
  <task_id>: <reason>`); NO completed/approved message fires; a `p1`
  blocker message names the refusal reason instead. Before this fix, this
  branch unconditionally sent the completed/approved message and (with
  `--auto-release-success`) released the claim regardless of whether the
  done transition succeeded, and with `--no-auto-release-success`
  specifically nothing else touched `failure_count`/`held_count`, so the
  loop's `ok` could read `True` with a refused done hidden inside it.
  `ok = failure_count == 0 and held_count == 0 and refused_count == 0 and
  inbox_blocked_count == 0` now folds all three non-clean outcomes in
  identically -- a held OR a refused run drives a nonzero process exit, it
  can never be read as silent success.

This is an honest regression from "exit 0 = done": worker tasks that used to
silently complete without landing anything now pile up in review instead.
That is the point -- it is visible and recoverable, where the old behavior
was neither.

## The gate

`scripts/forge/gates/workboard_evidence_gate.py` is unpinned this phase and
**CI-enforcing now**: wired into `.github/workflows/gates.yml`'s diff-range
job (`--base "$BASE_SHA" --head "$HEAD_SHA"`), and registered in
`tests/test_every_enforcing_gate_can_fail.py`'s `RED_PATH_CASES` under key
`"workboard_evidence_gate.py"` -- the enforcing-gate ratchet demands every
registered gate demonstrably fail on a real violation, and this one does
(fixture forces a `status=done` transition with no `evidence=` field).

It works from the **board diff itself** (staged git index locally, a
base..head ref in CI), not from any single call path -- deliberately,
because `scripts/crew/workboard/issue.py` (pinned, untouched this phase)
carries its own parallel `_set_task_status` line-mutator with zero evidence
plumbing. Nothing routes a `done` transition through it today, but the
gate's diff-based design does not depend on that staying true.

Verdict handling, tested in both failure directions:
- every task whose NEW status is `done` must carry an `evidence=` field
  UNLESS the OLD status was ALSO `done` AND its `evidence=` value is
  byte-for-byte unchanged (CORRECTED, whole-branch review fix wave -- see
  "Notable catches", THE BLIND WINDOW, below: status alone was not enough);
- `verified` -> PASS; `attested` -> PASS with a printed
  `ATTESTED-NOT-VERIFIED` note; a `failed` verdict whose `reason_code` is in
  `UNAVAILABLE_REASON_CODES` -> PASS with an `UNAVAILABLE` note (run-kind
  evidence needs `--run-store-db` passed to the gate to be independently
  re-checked at all -- CI does not pass it today, so run-kind evidence
  currently always PASSES unverified in CI);
- any other `failed` reason, a missing `evidence=` field, or a value that
  does not parse -> FAIL, naming the task.

It always prints how many Active Task lines it consulted and how many
done-transitions it found, even when both are zero -- an empty diff is a
fact worth stating, not a silent pass.

## Notable catches of the phase (the loop worked)

- **First-commit-verifies attack**: the repo's very first commit -- unrelated
  to any task by construction, since it predates every task -- verified as
  evidence for ANY `task_id` handed to it, because ancestry alone said
  nothing about binding. Fixed by requiring `task_id`/`not_before` binding
  for `"verified"`; landed-but-unbound now downgrades to `"attested"`.
- **Substring binding**: `task_id` binding first used a plain substring
  check, so a short id like `T-1` or `122` falsely bound through any longer
  id that happened to contain it (`T-12`; `116-117-122-130`) -- this repo's
  real `THOMAS-GITHUB-ISSUE-122` / `THOMAS-GITHUB-ISSUES-...-122-...` naming
  makes the collision real, not theoretical. Fixed with a whole-token
  boundary regex that treats `-` as an id character, not a delimiter (a
  plain `\b` would not have been enough for the same reason).
- **Silent hold in real deployment**: the worker's stdout is DEVNULL'd by the
  bootstrap spawn, so a held task's printed warning was invisible in
  practice; worse, the completed/approved message still fired and
  `require_done_state`'s no-op silently released the claim anyway. Fixed:
  a hold now means no release, its own blocker message, and a nonzero exit
  -- the loop can no longer look clean while a task sits unproven.
- **False expiry on absent infrastructure**: the first sweep implementation
  treated `verify_evidence`'s `db_path=None` short-circuit (and, in a second
  review round, a `git`-unavailable `OSError`) as a positive `"failed"`
  verdict, which would have expired legitimately-verified run/commit
  evidence just because the operator running the sweep forgot a flag or
  `git` wasn't reachable. Fixed with `reason_code` membership in
  `UNAVAILABLE_REASON_CODES` routing those cases to `skipped`, never
  `candidates`. **Widened, whole-branch review fix wave**: `git merge-base
  --is-ancestor` also exits nonzero when the TARGET ref (`dev`) itself does
  not resolve in the checkout (a shallow clone, a worktree without the
  branch, or the common PR-CI shape with only `refs/remotes/origin/dev`) --
  that case fell through to an unmarked `"failed"` too, so the sweep
  expired verified dones on any checkout where `dev` does not resolve
  (reproduced in `nodev.py`). Fixed by probing
  `git rev-parse --verify dev^{commit}` on any nonzero merge-base exit:
  target-unresolvable now routes to `REASON_CODE_GIT_UNAVAILABLE` (skip);
  an unknown/non-ancestor sha on an otherwise-resolvable target is
  unchanged (`"failed"`, empty `reason_code` -- T1 contract 2, pinned).
- **Recycled evidence -- THE BLIND WINDOW (whole-branch review, CRITICAL,
  reproduced)**: reopening a task left the prior cycle's `evidence=` field
  on the line untouched, so a hand-flip straight back to `done` (bypassing
  `set_task_status`) inherited a possibly-genuinely-verified but entirely
  stale proof. The per-cycle strip fix above (`claim_evidence.strip_evidence`
  on every FROM-`done` transition) closed the OBVIOUS shape of this, but a
  reviewer reproduced a second, deeper one: the gate's original scoping
  rule was "new status is `done` AND old status was not already `done`" --
  full stop, no look at evidence. A reopen (`done -> queued`, strip fires)
  followed by a hand-reflip straight back to `status=done`, with the
  intermediate `queued` state NEVER COMMITTED, reads as `done` -> `done` in
  the one board diff the gate actually sees -- both sides `"done"` -- which
  the old rule treated as an unchanged standing done and skipped entirely.
  A done with ZERO evidence landed clean (reproduced in `blindwindow.py`).
  The identical blind spot let evidence be SWAPPED on a standing done with
  no reopen at all. Fixed by adding evidence-equality to the scoping test
  itself (`_done_transitions` in `workboard_evidence_gate.py`): in scope
  whenever new status is `done` AND (old status != `done` OR old evidence
  != new evidence). The strip alone was necessary but not sufficient; the
  gate needed to be able to SEE an evidence change directly, not assume the
  strip already made it visible as a status change.

## Follow-ups (not done in this phase, carried forward)

- **`repo_root` asymmetry (whole-branch review, finding 4)**:
  `reactivate.set_task_status`'s commit-evidence verification passes a
  module-level constant `ROOT` (`scripts/crew/tasks/reactivate.py`'s own
  `_REPO_ROOT`, hardcoded at import time) to `claim_evidence.verify_evidence`
  -- NOT derived from the `workboard_path` argument the caller actually
  passed in. `workboard_evidence_gate.py`'s `run_check`, by contrast, takes
  `repo_root` as an explicit parameter matched to wherever the board it is
  checking actually lives. Harmless in production (the real workboard only
  ever lives in the real checkout), but every fixture-repo test in this
  phase has to `monkeypatch.setattr(reactivate, "ROOT", fixture_repo["root"])`
  to work around it, and it means `set_task_status` cannot correctly verify
  evidence for a workboard living in a DIFFERENT checkout (a worktree, a
  clone under test, a future multi-repo setup) than the one the calling
  process happens to be running from. A future change should thread
  `repo_root` through `set_task_status` explicitly, defaulting to `ROOT`
  for backward compatibility, the same shape `evidence_db_path` already
  uses for the run-store side.
- **Commit-kind enforcement is effectively push-to-dev only (whole-branch
  review, finding 5)**: `VERIFY_TARGET_BRANCH = "dev"` in
  `claim_evidence.py` is a bare ref name, and `git merge-base --is-ancestor
  <sha> dev` only resolves it if a local branch literally named `dev`
  exists in the checkout. A PR-triggered CI checkout typically has only
  `refs/remotes/origin/dev` (no local `dev` branch), so `_ref_resolves`
  (the finding-2 fix above) correctly downgrades EVERY commit-kind
  evidence check on a PR to `REASON_CODE_GIT_UNAVAILABLE` -- an honest
  skip now, rather than a false failure, but still not an actual
  verification. In practice, commit-kind evidence is only ever genuinely
  RE-CHECKED by `workboard_evidence_gate.py` on a push-triggered run to
  `dev` itself (where the bare name really does resolve), not on the PR
  checks that run before a merge. This repo already has the fix SHAPE for
  this, precedented and working: `scripts/forge/gates/release_update_gate.py`'s
  `_merge_base_with_canonical` (line 196) tries an ordered fallback list of
  ref names -- `("dev-origin/dev", "origin/dev", "dev", "origin/main",
  "main")` -- before giving up. `claim_evidence.py`'s `VERIFY_TARGET_BRANCH`
  resolution (and `_ref_resolves`'s probe) should grow the same fallback
  list rather than trying the bare name alone. Out of scope for this fix
  wave; flagged, not fixed.
- **A second, incidental evidence strip on the reactivation path (finding
  8)**: `reactivate._reactivate_task` (the Up-For-Grabs -> claimed
  reclaim/reactivation flow) rebuilds a task's Active Task line from
  scratch via `workboard_issue._format_active_task(task_id=..., agent=...,
  scope=..., summary=..., status="claimed")`, which writes ONLY the five
  canonical fields (`task_id`, `agent`, `scope`, `summary`, `status`) --
  confirmed by reading it (`scripts/crew/workboard/issue.py`). Any
  `evidence=`/`evidence_recorded_at=` field is dropped as a side effect of
  full-line reconstruction, independent of `claim_evidence.strip_evidence`
  and the FROM-`done` transition check that calls it. This is a SECOND
  place the per-cycle rule happens to hold today, not a deliberate,
  documented enforcement point -- worth knowing about so a future refactor
  of `_format_active_task` (e.g. one that starts round-tripping unknown
  fields, mirroring `claim_evidence`'s own line-grammar helpers) does not
  accidentally start preserving evidence through a reactivation and
  reopen the recycled-evidence class of bug from a different angle.
- **Release-recovery may miss presence-gate refusals (note-only, finding
  6)**: `claim_ops.release` runs a `_presence_gate` check
  (`scripts/crew/workboard/claim_ops.py`) that can refuse a release when
  the repo presence monitor detects other active or unregistered agents.
  Flagged by review as a case where a presence-gate refusal during claim
  release leaves the board in a correct state (the claim legitimately
  stays put) but the overall process return code does not reliably reflect
  the refusal in every release-recovery call site. Not independently
  re-derived end-to-end in this fix wave (note-only per the review); worth
  a dedicated audit of every `_release_claim_safe`/`workboard_claim.release`
  call site's error-propagation path.
- **`--ttl-hours` has no meaningful floor (note-only, finding 10)**:
  `claim_cleanup.py --evidence-sweep --ttl-hours` only enforces `> 0`
  (`if args.ttl_hours <= 0: ... "--ttl-hours must be > 0"`) -- confirmed by
  reading it. A value like `0.0000001` passes that check but defeats the
  TTL's purpose as a grace period, expiring evidence essentially
  immediately after it is recorded. A future change should enforce a real
  minimum (e.g. a fraction of an hour, not an arbitrarily small positive
  float).
- **Run-metadata task stamping**: no caller stamps a claiming `task_id` into
  a run's `session_id`/`profile`/`mode` text, so run-kind evidence can only
  reach `"verified"` via `not_before` today. A future change should stamp
  `task_id` at `create_run` time (or add a dedicated run_store column) so
  run evidence can bind by name the same way commit evidence does.
- **`--run-store-db` in CI**: `.github/workflows/gates.yml`'s gate
  invocation does not pass `--run-store-db`, so run-kind evidence in CI
  always PASSES as `UNAVAILABLE` (unverified) rather than being
  independently re-checked. Wiring a CI-reachable db path was out of scope
  for this phase.
- **`not_before` re-check asymmetry**: the sweep re-verifies with `task_id`
  only, never `not_before` (the original claim-time timestamp isn't
  persisted on the workboard line), so evidence that verified at the done
  transition via `not_before` downgrades to `"attested"` on every later
  sweep pass. Harmless today (attested never expires) but worth closing if
  the sweep ever needs to distinguish "still verified" from "was verified
  once."
- **`active_folders.py` debt**: a pre-existing 1446-line file became visible
  to the monolith guard as a side effect of this phase's gate-visibility fix
  (task 2). Not created by this phase; deferred, untouched.
- **Doubled-trailer cosmetic, CORRECTED COUNT (whole-branch review flagged
  the understatement)**: this previously said commit `1e88f198` alone had
  a doubled `Thomas-Agent: claude` trailer. A claims-that-verify phase must
  not understate a claim about itself. Re-verified directly against the
  tree: `git log --format=%H fbd22be0^..42343a30`, then `git log -1
  --format=%B <sha> | grep -c "^Thomas-Agent: claude$"` for every commit in
  that range (18 commits total, inclusive of `fbd22be0`) -- **13 of 18**
  carry the doubled line (once mid-body, once in the real trailer block at
  the end), 5 do not. (Review flagged this as "13 of 19"; this session's
  own recount of the same inclusive range found 18 commits, not 19 -- the
  core finding, that it is far more than 1, is confirmed either way.)
  Cosmetic artifact of the scoped-fallback commit tooling; the real
  trailer block at the end of each message is intact and correct in every
  case. Deferred, no functional impact.
- **Promotion path**: `workboard_evidence_gate.py` is unpinned and not yet in
  `agent_safety.toml`'s `enforcement_scripts`, and `commit.py`'s
  `LOCAL_GATE_COMMANDS` does not run it locally -- CI is the only enforcement
  today. See `plans/thomas/tasks/PRAXIS-PHASE14-BREAKGLASS/batch.md` for the
  prepared promotion.
