# Phase 2 Repairs, Batch 1 (spec phase 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** The first repair batch under working instruments: the incident ledger stops lying about its own backlog (stale landed-scope records closed under the loop's law, recurring work gets vocabulary), salvage debris dies with death records, and the claims-verification system's two disclosed verification gaps close.

**Evidence basis:** `.superpowers/sdd/2026-08-25-phase2-recon/recon.md` (pinned to fce87aa3) — every task below cites its section. Instruments, not verbal reports, ranked this batch (spec phase 2 rule).

**What is deliberately NOT here (owner decisions, queued in the closure report, untouched by this batch):** praxis-unbypassable E1 deferral ruling (recon #2); the hardening-2026-06-12 phantom close (recon #3); audit-24h-backstop assign/retire (recon #9); re-baseline-vs-split for the 21 non-orphan monolith violations (recon #4). Recon #8 (evidence gate local enforcement) is ALREADY covered by the amended tap #3 batch — no work here.

**Tech Stack:** Python 3.12, pytest, git. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-24-praxis-first-design.md` §2. Owner delegation 2026-08-24 active.

## Global Constraints

All prior plans' Global Constraints (wrapper commits, park CHANGELOG, no double quotes, ruff, sentence-named tests, <800-line files for NEW/edited-unbaselined files, no `*_part*.py`/`exec()`), plus:
- **The closure grammar is law, including for us:** records close ONLY via `gate:` / `tombstone:` / `accepted-risk:` lines that RESOLVE. `commit:` is NOT a closure form — the recon proposed it and it is illegal by design. The landed-scope records close via an expiring accepted risk (Task 1) so REOPEN DUE resurfaces them.
- **Accepted-risk owner field under delegation:** records created this batch set `owner` to `calvin (standing delegation 2026-08-24, claude-recorded)` — honest about who accepted and under what authority; the closure report lists every risk recorded so it can be vetoed. Expiry dates are REAL and near (≤3 months) — the point is resurfacing, not archiving.
- **Deletions go through the graveyard:** every file deleted in this batch gets a `record_death` entry (scripts/forge/graveyard.py) in the same commit, per the phase-1.2 practice. The merge-resurrection gate must know these deaths.
- **Live server dormancy:** Task 3 touches server-side code (`chat_v2_run_store.py`). Changes are dormant until the next server restart — state this in the task's report; NEVER restart or verify against :8899. CHANGELOG entry per commit (the phase-1.5 lesson — tests/docs/plans don't trip the gate's counter, write the entry anyway).
- Fixture-only tests; never the real problems/ dir or WORKBOARD in tests.

---

### Task 1: The ledger stops lying — landed-scope closures and recurring vocabulary

**Files:**
- Modify: `scripts/crew/brief/incident_surfacing.py` (recurring vocabulary); the 9 `plans/thomas/problems/THOMAS-GITHUB-ISSUE*/PROBLEM.md` records (status → resolved + closure line); `plans/thomas/problems/ELECTRON-BUMP-RECURRING/PROBLEM.md` (recurring marker); `docs/ops/accepted_risks.json` via the registry CLI (one new risk record)
- Test: extend `tests/test_the_next_scar_costs_one_incident.py`

**Behavior:**
- **Recurring vocabulary (recon #10):** a PROBLEM.md header line `recurring: <one-line cadence statement>` (exact grammar implementer's choice, mirroring the existing header conventions) makes incident_surfacing report the record in a NEW `RECURRING: N standing` line — excluded from the open-without-closure count, never from existence. The closure gate needs NO change (recurring records never transition to resolved; verify the gate ignores the new header line — add a test proving a recurring record edit doesn't trip it).
- **The landed-scope class (recon #1):** record ONE accepted risk via the registry CLI: reason states the class ("nine task records' scope landed in ea788bac 2026-08-14 without closure; no practice yet auto-closes landed-scope records"), refs the recon, expires 2026-11-30. Then close all 9 records: status resolved + `- closure: accepted-risk:<the-id>`. The closure gate itself validates this in CI — the loop eating its own cooking. Verify: `incident_surfacing` drops from 25→16 open, RECURRING: 1, REOPEN DUE: 0 — quote the actual line in the report.
- **ELECTRON-BUMP-RECURRING** gains the recurring marker (status stays up_for_grabs — it is standing work, not an open scar).

**Contracts (tests pin):** recurring record excluded from open count + shown in RECURRING line (fixture); recurring + resolved-with-closure both handled; recurring header ignored by the gate; the real 9-record closure validated by running the gate in diff-range mode over the actual commit (self-check step, not a fixture).

- [ ] Steps: failing tests → instrument change → registry record + 9 closures + marker → gate self-check green → ruff → wrapper commits (≤3 counted code files; the 9 PROBLEM.md edits are plans/, uncounted) → subject: `fix(crew): the ledger stops lying - landed scope closes under an owned risk, recurring work gets a name`

### Task 2: Salvage debris dies with death records (recon #4, orphan half)

**Files:**
- Delete: `thomas/server/app_part03.py`; `apps/site/src/app/globals_part01.css`, `globals_part02.css`, `globals_part03.css`
- Modify: `docs/ops/graveyard.json` via `record_death` (4 entries, same commit)
- Test: extend an existing suitable test file or create `tests/test_salvage_debris_stays_dead.py`

**Behavior:** the four files are proven orphans (recon 3c): `app_part03.py` is unreachable — `thomas/server/app.py:16-25` activates its loader only when ALL FOUR `app_part0N.py` exist and only one does; the three `globals_part0N.css` duplicate the still-present, still-full `globals.css`. VERIFY both facts fresh at HEAD before deleting (the repo is live; re-read app.py's guard and re-glob the part files — if the facts changed, STOP and report instead of deleting). Each deletion gets a graveyard death record naming cause `salvage-debris` and the recon as evidence. Do NOT touch app.py's loader branch itself (it self-neutralizes and removing it is a behavior-adjacent edit this batch doesn't need); do NOT touch `globals.css` or the 21 other monolith violations (owner decision, queued).

**Contracts:** files gone at HEAD; graveyard records exist and load; a test asserts `app_part03.py` and `globals_part01.css` MUST NOT exist (the phase-1.2 anti-resurrection pattern — merge-resurrection gate covers the rest); monolith violation count drops 23→21 (assert by running the guard).

- [ ] Steps: fresh verification → failing MUST-NOT-exist test → delete + record deaths (same commit) → guard count check → ruff → wrapper commit: `chore(server): salvage debris dies on the record - four orphans, four tombstones`

### Task 3: The verification gaps close (recon #6 + #7)

**Files:**
- Modify: `scripts/crew/workboard/claim_evidence.py` (fallback ref list); `thomas/server/routes/chat_v2_run_store.py` (`start_chat_v2_run` stamps task_id); `.github/workflows/gates.yml` (`--run-store-db` wiring)
- Test: extend `tests/test_a_done_claim_carries_proof_or_it_is_not_done.py` (or the file's current name — find it)

**Behavior:**
- **Commit-kind PR verification (recon #6):** replace the bare `VERIFY_TARGET_BRANCH = "dev"` resolution with the ordered-fallback pattern precedented at `scripts/forge/gates/release_update_gate.py:196` (`dev`, `origin/dev`, then the documented fallbacks). Semantics preserved: still `git_unavailable` (honest skip) when NOTHING resolves; the change is that a PR checkout with `origin/dev` now VERIFIES instead of skipping.
- **Run-kind binding (recon #7a):** `start_chat_v2_run` accepts/stamps an optional `task_id` into run metadata so run-kind evidence can verify by exact-token binding, not only `not_before`. Find the callers; thread it where a task id is actually in scope; leave others passing None (honest absence). Server code — dormant until restart; say so in the report.
- **CI run-store (recon #7b):** gates.yml passes `--run-store-db` to the evidence gate job pointing at the repo's run-store path IF a checkout can have one; if CI can structurally never have the DB, then instead of fake wiring, document that in the workflow comment AND in the gate's UNAVAILABLE note — an honest `UNAVAILABLE (ci-no-db)` beats a flag that never resolves. Implementer decides with evidence and states it.

**Contracts:** fixture repo with only `origin/dev` → commit-kind verifies; neither ref → git_unavailable skip unchanged; run created with task_id → readable in metadata + evidence binds exact-token; without → not_before path unchanged; CI decision documented and tested for whichever branch was taken.

- [ ] Steps: failing tests → implement (3 files, ≤3 counted per commit — split if needed) → green → ruff → wrapper commit(s): `fix(crew): a PR can prove a commit landed - and a run knows its task`

### Task 4: The self-review endpoint stops looking dead (recon #5)

**Files:**
- Modify: whichever `thomas/server/routes/*` module backs `/api/self-review` (recon did not trace it — find it first) 
- Test: sentence-named additions in the route's existing test file

**Behavior:** today the endpoint runs a 15-30s synchronous LLM generation; any caller with an ordinary timeout sees HTTP_000 — the misreporting family's exact shape (working instrument reads as down). Fix with the SMALLEST honest change, implementer's evidenced choice between: (a) cache-with-TTL — serve the last generated report instantly with a `generated_at` stamp and refresh in the background; (b) async split — `202 + Location` poll pattern; or (c) if the module already has an obvious cache/refresh convention, follow it. Requirement either way: a normal-timeout GET must return HTTP 200 with honest content (a stamped report or an explicit `generating` status body) — never hang past a few seconds, never fabricate. Server code — dormant until restart; NEVER verify against :8899; test via the route's unit-test harness (aiohttp test client per existing convention).

**Contracts:** fast path returns 200 within the harness's default timeout with a timestamped payload; slow generation happens off the request path (or behind the poll); a failed generation yields an honest error status in the payload, never a silent stale-forever cache (staleness must be visible via the stamp).

- [ ] Steps: trace the handler → failing tests → implement → green → ruff → wrapper commit: `fix(server): self-review answers fast and stamps its age - slow is not down`

### Task 5: Batch closure

**Files:**
- Create: `plans/thomas/tasks/PRAXIS-PHASE2-BATCH1/status.md`

**Behavior:** what landed with evidence; the live INCIDENTS/RECURRING lines quoted fresh; the accepted risk recorded (id, expiry, veto instruction); the owner-decision queue restated (E1 ruling, phantom record, audit-24h-backstop, 21 monolith violations); what is dormant until restart (Tasks 3b, 4); the spec's exit criterion restated (a month organic without a new family instance — this batch starts the clock, it does not finish it). Second person for owner text; no name; no ability characterization.

- [ ] Steps: verify every claim against tree → write → wrapper commit: `docs(phase2): batch one lands - the ledger tells the truth it enforces`

## Self-review notes
- Spec §2 fidelity: repairs ranked by instruments ✔ (recon-cited per task); fixes land under phase-1 protection ✔ (closure gate validates Task 1's own closures in CI; graveyard records Task 2's deaths; evidence system improved by Task 3 verifies future claims).
- The one genuinely new mechanism (recurring vocabulary) is instrument-side only — the gate is untouched by design and a test proves it stays untouched in behavior.
- Owner decisions are queued, not made: the accepted risk is recorded under the standing delegation with a veto path, near expiry, and REOPEN DUE as the enforcement that it cannot rot silently.
