# Claims That Verify Implementation Plan (spec phase 1.4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** "Done" becomes a checked status: the transition to done requires machine-verifiable evidence, a gate refuses evidence-free done transitions from landing, and unproven done claims expire back to the queue.

**Architecture:** An evidence library (`scripts/crew/workboard/claim_evidence.py`, unpinned) defines three evidence kinds — `commit:<sha>` (verified: ancestor of dev), `run:<run_id>:<from>-<to>` (verified against the phase-1.3 run_store spine: run exists, finalized ok, seq range present), `gate:<name>:<exit>` (attested-not-verified in this phase; labeled as such, never presented as verified). The done transition (worker.py / reactivate.py, both unpinned) demands evidence and records it; a new unpinned gate refuses WORKBOARD diffs that flip a task to done without well-formed evidence (CI-wired now; commit.py/pin promotion queued for the next tap); expiry extends claim_cleanup.py's existing apply-plumbing with an evidence-sweep driving the already-legal done→queued transition. No pinned file changes in this phase — promotions ride the Task 5 batch doc.

**Corrections to the recon this plan is built on:** phases 1.2 and 1.3 ARE landed (graveyard live with 705 records; run_store extended to 1007 lines with model/request-response + mutation events, capture dormant until restart) — the recon's "not yet built" claims are wrong; run-store evidence is a real kind from day one, though sparse until the next server restart. Everything else in the recon was file:line-verified.

**Tech Stack:** Python 3.12, pytest, git. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-24-praxis-first-design.md` §1.4. Owner delegation 2026-08-24 active.

## Global Constraints

All prior plans' Global Constraints (wrapper commits, park CHANGELOG, no double quotes, ruff, sentence-named tests, <800-line files, no `*_part*.py`/`exec()`), plus:
- **Touch NO pinned file:** `workboard_claims.py`, `workboard_task_problems.py`, `issue.py`, `problem_record.py`, `workboard_agent_claim.py`, `workboard_inbox*.py`, `workboard_changed_files.py`, `commit.py`, manifest, agent_safety.toml. Evidence storage must be schema-tolerant: FIRST verify whether `workboard_claims.py`'s validator rejects unknown fields on Active Task lines (read `evaluate_claims`); if extra fields are tolerated, `evidence=` rides the task line; if rejected, evidence lives in the task's `plans/thomas/problems/<id>/PROBLEM.md` record (unpinned files) with the task line untouched. The chosen storage is a Task 1 deliverable, stated with the validator evidence.
- **WORKBOARD.md housekeeping FIRST:** the file carries a benign pending diff (releases both live claim rows, bumps Task-Problems timestamps, acks historical messages). Before any 1.4 code writes WORKBOARD, land that state as one disclosed housekeeping commit (subject notes the content predates this plan and reflects operational truth; the release-rows mean zero live claims exist). Verify zero live claims after landing.
- **The blame-based freshness detector is broken by design** (uncommitted lines read age-0.00h) — new expiry logic must key on explicit recorded timestamps and evidence validity, NEVER on `git blame` of the line.
- **New enforcing gates register red-path selftests in RED_PATH_CASES** (tuples) — the ratchet refuses them otherwise.
- Live server dormancy rules; temp stores in tests; never the real WORKBOARD in tests (fixture boards only).

---

### Task 1: The evidence library

**Files:**
- Create: `scripts/crew/workboard/claim_evidence.py`
- Test: `tests/test_a_done_claim_carries_proof_or_it_is_not_done.py`

**Interfaces (Tasks 2-4 consume):**
- `parse_evidence(raw: str) -> Evidence` — grammar `kind:payload`; kinds `commit` (payload 7-40 hex), `run` (payload `<run_id>:<from>-<to>`), `gate` (payload `<gate_name>:<exit_code>`); malformed -> ValueError naming the defect.
- `verify_evidence(ev: Evidence, repo_root: Path, db_path: Path | None = None) -> Verdict` where `Verdict` carries `status` in {"verified","attested","failed"} + `reason` (one sentence, printable). commit: verified iff `git merge-base --is-ancestor <sha> dev` (run in repo_root); run: verified iff run exists in the run_store DB, finalized ok, and the seq range is present in its replay; gate: ALWAYS "attested" with reason stating this kind is recorded but not independently verified in phase 1.4.
- `format_evidence_field(ev) -> str` + the storage-location decision (see Global Constraints) implemented behind `record_evidence(task_id, ev, ...)` / `read_evidence(task_id, ...)` so Tasks 2-4 never care where it lives.

**Contracts (tests pin):** (1) grammar round-trips; malformed loud; (2) commit verification against a fixture repo: ancestor sha -> verified, non-ancestor -> failed with reason, unknown sha -> failed; (3) run verification against a temp run_store: finalized-ok run with the range -> verified; unfinalized or missing range -> failed; (4) gate kind -> attested, never verified; (5) record/read round-trip in the chosen storage with the validator evidence documented in the module docstring.

- [ ] Steps: failing tests → implement (~250 lines) → green → ruff → wrapper commit: `feat(crew): evidence has a grammar and a verifier - done gets something to be checked against`

### Task 2: Evidence at the transition

**Files:**
- Modify: `scripts/crew/workboard/worker.py` (the review→done flip at ~:769-789)
- Modify: `scripts/crew/tasks/reactivate.py` (`set_task_status` gains optional `evidence` plumbing)
- Test: extend the sentence-named test file

**Behavior:** the done transition requires evidence: `set_task_status(..., status="done", evidence=<raw>)` parses + verifies; "verified" proceeds and records; "attested" proceeds, records, and prints an ATTESTED-NOT-VERIFIED line; "failed"/absent -> the transition is REFUSED with the verdict reason (task stays in review). worker.py's auto-done passes `commit:<sha>` when its pipeline landed a commit, else refuses to auto-done and leaves the task in review with a loud line (an honest regression from auto-done-on-exit-0 — that is the point). CLI surfaces that can set done (find them: claim.py/manager paths) gain `--evidence`. HOUSEKEEPING FIRST step lands the pending WORKBOARD diff per Global Constraints.

**Contracts:** (1) done without evidence refused, task remains review, exit nonzero, reason printed; (2) done with ancestor-commit evidence proceeds + recorded + readable; (3) attested gate evidence proceeds with the label; (4) failed verification refused with reason; (5) worker auto-done: pipeline-with-commit passes sha; pipeline-without-commit leaves review loudly (test both); (6) the housekeeping commit landed and zero live claims confirmed.

- [ ] Steps: housekeeping commit → failing tests → implement → green → ruff → commits (≤3 counted code files each): `feat(crew): done requires proof at the moment of the claim`

### Task 3: Expiry of the unproven

**Files:**
- Modify: `scripts/crew/workboard/claim_cleanup.py` (new evidence-sweep mode; reuse its apply/release plumbing, NOT its blame-based detector)
- Test: extend the test file

**Behavior:** `claim_cleanup.py --evidence-sweep [--ttl-hours N] [--apply]`: walks Active Tasks in status=done; for each, `read_evidence` + re-verify; missing/failed evidence AND a recorded-done timestamp (Task 2 records one at transition time in the evidence storage) older than TTL -> drive done→queued (legal transition), move to Up-For-Grabs with a line naming the failed verdict, emit a workboard message to the claiming agent. Dry-run default prints the would-expire list. Attested evidence does NOT expire in phase 1.4 (stated in --help). Re-verification means a commit that later vanished from dev expires its claim — test with a fixture repo whose sha is removed.

**Contracts:** (1) done-with-verified-evidence never expires; (2) done-without-evidence past TTL expires to queued + Up-For-Grabs + message (fixture board); (3) evidence that no longer verifies expires; (4) dry-run mutates nothing; (5) blame-based detection provably unused in the new path (no `git blame`).

- [ ] Steps: failing tests → implement → green → ruff → commit: `feat(crew): a done that cannot re-prove itself goes back in the queue`

### Task 4: The gate

**Files:**
- Create: `scripts/forge/gates/workboard_evidence_gate.py` (unpinned this phase)
- Modify: `tests/test_every_enforcing_gate_can_fail.py` (RED_PATH_CASES tuple entry)
- Modify: `.github/workflows/gates.yml` (diff-range job, existing style)
- Test: `tests/test_a_task_cannot_land_as_done_without_evidence.py`

**Behavior:** staged mode: if the staged WORKBOARD.md diff introduces/changes an Active Task line to status=done (or the evidence storage marks a done), the evidence must parse and not verify as failed (gate re-verifies commit kind cheaply; run kind verified against the db if readable, else attested-pass with a printed note; never silently green). Diff-range mode for CI. Honors runtime_protection_disabled. Prints counts consulted (the honest zero).

**Contracts:** (1) done-without-evidence staged -> FAIL naming the task; (2) done-with-verified-evidence -> PASS; (3) malformed evidence -> FAIL naming the grammar defect; (4) non-done WORKBOARD edits pass untouched; (5) RED_PATH_CASES entry through the real shim; ratchet green, no baseline delta.

- [ ] Steps: failing tests → implement → RED_PATH entry + gates.yml wiring → ratchet green → ruff → commit: `feat(gates): the workboard refuses a done it cannot check`

### Task 5: Closure + the phase-1.4 batch

**Files:**
- Create: `plans/thomas/tasks/PRAXIS-PHASE14-CLAIMS/status.md`
- Create: `plans/thomas/tasks/PRAXIS-PHASE14-BREAKGLASS/batch.md`

**Behavior:** status.md: what verifies today (commit, run kinds), what is attested-only (gate kind), what expires and what does not, the worker auto-done behavior change stated plainly, follow-ups (gate-rerun evidence kind; run evidence post-restart; promotion path). batch.md (PREPARED, phase-0 format): promote `workboard_evidence_gate.py` into enforcement_scripts + manifest re-bless; commit.py LOCAL_GATE_COMMANDS entry (staged-files signal — correct for this gate); optional promotion of `evidence` to a required field in pinned `workboard_claims.py` ONLY as an owner decision with the trade-off stated (breaks legacy boards). Second person for owner text; no owner name. STATUS: PREPARED line verbatim.

- [ ] Steps: verify every claim against the tree → write both → wrapper commit: `docs(phase14): done means checked - and the batch that makes it law awaits your tap`

## Self-review notes
- Spec §1.4 coverage: evidence-required done ✔ (T2), gate refusal ✔ (T4), expiry ✔ (T3), log-derived proof ✔ (run kind, real since 1.3; sparse until restart — stated); "gate results" evidence honestly attested-not-verified this phase.
- No pinned files touched; promotions batched for the tap. The recon's not-yet-built errors corrected above.
- The worker auto-done change is the phase's one behavior change to live tooling — loud, tested both ways, and the honest core of the phase.
