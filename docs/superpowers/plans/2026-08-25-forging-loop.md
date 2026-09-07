# Forging Loop Implementation Plan (spec phase 1.5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Every incident ends in a practice or an explicit, expiring acceptance: a closure gate refuses to let a problem resolve until its record references a landed gate, a tombstone, or an owner-accepted risk — and an expired acceptance re-opens the incident.

**Architecture:** A new accepted-risks registry (`docs/ops/accepted_risks.json` + `scripts/forge/accepted_risks.py`) copies the graveyard's enforced-registry pattern byte-for-byte (append-only, file-locked, atomic replace, loud SystemExit on malformed) with the `owner/reason/reviewed_on/expires_on` field shape the mutating-route-exceptions gate already enforces elsewhere. A closure gate (`scripts/forge/gates/problem_closure_gate.py`, patterned on `workboard_task_problems.py`) refuses a task's transition to resolved unless its `PROBLEM.md` carries a `closure:` reference that RESOLVES: `gate:<filename>` must exist in `RED_PATH_CASES`; `tombstone:<id>` must resolve in the graveyard; `accepted-risk:<id>` must resolve unexpired — expiry FAILS the gate, re-opening the incident. Capture-side, the problem template gains the closure vocabulary and session start surfaces open incidents without closure. The new gate registers in `RED_PATH_CASES` (the ratchet enforces the enforcer) and its promotion rides the already-PREPARED tap #3 batch, amended — one tap, both phases.

**Recon corrections honored:** all phase 0-1.4 artifacts verified present; `graveyard.py`'s docstring dangling-references a `MEMORY.md` that does not exist in this repo — cleaned up in Task 1.

**Tech Stack:** Python 3.12, pytest, git. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-24-praxis-first-design.md` §1.5. Owner delegation 2026-08-24 active.

## Global Constraints

All prior plans' Global Constraints (wrapper commits, park CHANGELOG, no double quotes, ruff, sentence-named tests, <800-line files, no `*_part*.py`/`exec()`), plus:
- **Touch NO pinned file** (issue.py, workboard_task_problems.py, workboard_claims.py, agent_safety.toml, manifest, .pre-commit-config.yaml, commit.py). The new gate's promotion AMENDS the PREPARED tap-#3 batch (plans/thomas/tasks/PRAXIS-PHASE14-BREAKGLASS/batch.md — unpinned doc), clearly sectioned as phase-1.5 additions.
- **Reuse, never rebuild:** graveyard.py's locking/atomicity/malformed-handling; claim_evidence's reason-code + UNAVAILABLE membership semantics (an unreadable registry is a loud pass-with-note in the gate, never silent green, never a refusal on absent infrastructure); the KV-bullet conventions; the RED_PATH tuple shape.
- **References must RESOLVE:** the closure gate verifies the referenced artifact exists (gate name in RED_PATH_CASES, tombstone id in graveyard.json, risk id unexpired in accepted_risks.json) — a closure string that names nothing is a FAIL naming the defect. This program's every phase found the same disease: strings that point at nothing.
- **startup_router.py is 1142 lines, over the soft cap, unbaselined** — any edit trips the monolith gate. The worker.py precedent stands: pay the debt with a move-only split (extract a coherent module, one-way imports, re-exports) BEFORE wiring the surfacing line, or place surfacing so the router needs zero edits if a clean seam exists (implementer investigates and states the choice with evidence).
- Fixture-only tests; live server dormancy rules.

---

### Task 1: The accepted-risks registry

**Files:**
- Create: `scripts/forge/accepted_risks.py`; Create (empty): `docs/ops/accepted_risks.json`
- Modify: `scripts/forge/graveyard.py` (docstring dangling-reference cleanup ONLY — one line)
- Test: `tests/test_an_accepted_risk_is_owned_dated_and_expires.py`

**Interfaces (Tasks 2-3 consume):**
- Schema `{"version":1,"records":[{"id":"YYYY-MM-DD-<slug>-<n>","owner":str,"reason":str,"reviewed_on":"YYYY-MM-DD","expires_on":"YYYY-MM-DD","refs":str|null}]}`; `record_risk(repo_root, owner, reason, expires_on, refs=None) -> id`; `load(repo_root) -> Risks` with `Risks.get(risk_id) -> record|None` and `Risks.is_expired(risk_id, today) -> bool` (missing id is None, never a silent False); CLI `record|list [--json]`.
- Contracts: (1) round-trip + append-only + unique ids; (2) malformed file -> SystemExit naming it; missing file -> empty + stderr NOTE (stdout stays JSON-parseable — the phase-1.3 lesson); (3) expires_on validated as a real future-or-today date at record time, loud on garbage; (4) is_expired boundary semantics matching monolith_guard's precedent (read it, match it, cite it in the docstring); (5) locking/atomic tests per the graveyard's (crash-between-temp-and-replace; lock contention).

- [ ] Steps: failing tests → implement (~250 lines, graveyard as template) → green → ruff → wrapper commit: `feat(forge): an accepted risk has an owner, a date, and an expiry - not a shrug`

### Task 2: The closure gate

**Files:**
- Create: `scripts/forge/gates/problem_closure_gate.py`
- Modify: `tests/test_every_enforcing_gate_can_fail.py` (RED_PATH_CASES tuple); `.github/workflows/gates.yml` (diff-range job, existing style)
- Test: `tests/test_an_incident_ends_in_a_practice_or_an_owned_risk.py`

**Behavior:** Scope: staged/diff-range changes to `plans/thomas/WORKBOARD.md` Task Problems entries reaching `status=resolved`, AND `plans/thomas/problems/*/PROBLEM.md` files whose header status becomes resolved. A resolving incident requires a `closure: <form>` line in its PROBLEM.md where form is `gate:<filename>` | `tombstone:<id>` | `accepted-risk:<id>`; the gate RESOLVES the reference (RED_PATH_CASES membership via import; graveyard/risks via their load()); unresolvable reference or expired accepted-risk -> FAIL naming the defect and, for expiry, the re-open instruction. Unreadable registry -> pass-with-printed-note via the UNAVAILABLE semantics (never silent). Already-resolved-unchanged lines out of scope; proof-change scoping per the phase-1.4 lesson (a closure line changed on a standing resolved is in scope). Honors runtime_protection_disabled; counts consulted printed.

- [ ] Steps: failing tests (all three forms resolve/pass; each form unresolvable/FAIL; expired risk FAIL with re-open text; unreadable registry note-pass; already-resolved-unchanged skip; closure-swap caught) → implement (~250 lines) → RED_PATH entry + gates.yml → ratchet green no delta → ruff → commit: `feat(gates): an incident may end in a practice or an owned risk - never a shrug`

### Task 3: Capture and surfacing

**Files:**
- Modify: `scripts/crew/tasks/plans.py` (`_build_problem_template` gains a `## Closure` stub stating the three forms + the rule)
- Create: `scripts/crew/brief/incident_surfacing.py` (count + list of open incidents lacking closure, reading problems/ + the registries)
- Modify: `scripts/crew/brief/startup_router.py` ONLY per the split constraint (or zero-edit seam — implementer's evidenced choice)
- Test: sentence-named additions

**Behavior:** the problem template teaches the vocabulary at creation time; session start prints `INCIDENTS: N open without closure` + the oldest three (honest zero printed as zero). If the router must be edited: move-only split first (worker.py precedent), wiring commit on top.

- [ ] Steps: failing tests → implement → green → ruff → commits (split separate if needed): `feat(crew): the next scar costs one incident - capture teaches closure, session start counts the open ones`

### Task 4: Closure docs + the amended tap

**Files:**
- Create: `plans/thomas/tasks/PRAXIS-PHASE15-FORGING/status.md`
- Modify: `plans/thomas/tasks/PRAXIS-PHASE14-BREAKGLASS/batch.md` (append a clearly-marked phase-1.5 section: problem_closure_gate promotion into enforcement_scripts + manifest re-bless count updated + .pre-commit-config wiring; run order integrated; smoke tests outside the protection-off window; STATUS stays PREPARED)

**Behavior:** status.md: the loop's shape (incident -> closure or owned risk; expiry re-opens), what enforces where (CI now, local after the tap), follow-ups (legacy PROBLEM.md files with dangling Outcomes drain via the gate only when touched — stated, not hidden; the audit-24h-backstop file's 30+ unclosed failure records as the known first customer). Second person for owner text; no owner name; STATUS PREPARED verbatim in the batch.

- [ ] Steps: verify claims against tree → write both → wrapper commit: `docs(phase15): the forging loop closes - and one tap makes both phases law`

## Self-review notes
- Spec §1.5 coverage: incident-record template ✔ (T3 extends the EXISTING enforced record rather than inventing one); ends-in-gate/tombstone/acceptance ✔ (T2's resolving references); owner-accepted risk with expiry that re-opens ✔ (T1+T2); the loop enforces itself ✔ (the closure gate is RED_PATH-covered).
- One tap covers phases 1.4+1.5 (batch amended, not multiplied) — deliberate kindness to the signer.
- The legacy-incident drain is passive (gate fires on touch) — stated honestly in T4 rather than claiming retroactive enforcement.
