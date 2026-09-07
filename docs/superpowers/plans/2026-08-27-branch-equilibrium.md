# Branch Equilibrium (spec phase 2 — the sprawl family's practice)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Branch sprawl stops being possible quietly: the trunk's syncability is checked and shouted every session; a branch becomes a recorded claim with an owner and an expiry that auto-archives; and the whole mechanism is proven by red-path tests plus a retroactive measurement of the repo's own history showing why every prior fix failed to move the number.

**Evidence basis (owner-confirmed problem, 2026-08-27):** the cleanup found dev 746 commits unpushed because pre-push gates had been failing silently for weeks; 63 local branches, 70 stashes (most named as desperate snapshots), 150+ remote branches; the owner's prior fixes (advisory rules, one-time cleanups, a janitor, a squash) each failed because they policed symptoms while landing work stayed expensive and forking stayed free — and the enforcement layer itself was silently non-enforcing until db808bdf. The owner asked: why did my fixes fail, what is the solution, and how can you test and prove it. Owner authorization: "Do it."

**Spec:** phase 2 (repairs under working instruments); this is the resurrection/undelivered-fix families' shared root. Owner delegation 2026-08-24 active. All prior Global Constraints apply (wrapper commits, no double quotes, no manual trailers, CHANGELOG entry per product-changing commit, fixture-only tests, pinned files untouched — enforcement promotion rides a tap batch, closure grammar is law).

---

### Task 1: The sprawl becomes an incident, and the trunk gets a voice

**Files:**
- Create: `plans/thomas/problems/branch-sprawl-equilibrium-2026-08-27/PROBLEM.md` (the class incident: mechanism, why prior fixes failed, the practice being built; closure comes in Task 4)
- Create: `scripts/crew/brief/trunk_health.py`
- Modify: `scripts/crew/brief/startup_signals.py` (one wiring call, the incident_surfacing seam precedent)
- Test: `tests/test_the_trunk_has_a_voice.py`

**Behavior:** session start prints one TRUNK line: `TRUNK: <N> unpushed | branches <local>/<remote> | stashes <N> | push-gate <ok|blocked: gate1,gate2|unchecked (age)>`. Counts are cheap live reads (for-each-ref, stash list, rev-list --count dev-origin/dev..dev — degrade honestly to `unknown (<reason>)` if a remote ref is absent; never fetch at session start). The push-gate field reads a CACHED last-battery-result file (written whenever the battery actually runs — find where the pre-push hook runs it and add the small result-drop there, unpinned paths only; if the hook script is pinned, write the cache from a wrapper the hook already calls, or ship the cache-writer and note the one-line hook wiring as tap material) with its age always shown; a stale or absent cache reads `unchecked (Nd)`, never a fake ok. Session start must never fail (incident_surfacing's hardening rules: classified degradation, no raises).

**Contracts:** honest zero; unknown-not-fake on missing remote; cache absent → unchecked; cache stale → age shown; blocked → gate names shown; startup never raises (fixture the failure modes).

- [ ] Steps: failing tests → implement → wire → green → ruff → wrapper commits → subject: `feat(crew): the trunk has a voice - unpushed work and blocked gates stop being invisible`

### Task 2: A branch is a claim that expires

**Files:**
- Create: `scripts/forge/branch_claims.py` + `docs/ops/branch_claims.json` (the accepted-risks registry pattern byte-for-byte: append-friendly, locked, atomic, loud on malformed; record = {branch, owner, purpose, created_on, expires_on ≤60d, refs})
- Create: `scripts/forge/gates/branch_claim_gate.py` (pre-push shape, dead_ref_gate precedent: pushing a NEW branch ref to any remote requires a live claim record; unclaimed → FAIL naming the remedy command; deletions and dev itself exempt; RED_PATH_CASES entry + gates.yml)
- Modify: `thomas/forge/branch_custodian.py` ONLY if unpinned (VERIFY against agent_safety.toml first — if pinned, ship the sweep as a standalone `scripts/forge/branch_sweep.py` the custodian can later adopt via tap): the sweep archives-then-deletes local branches whose claim is expired or absent after a 7-day grace (archive ref + graveyard death record per the phase-1.2 practice; NEVER delete unarchived), and reports counts honestly.
- Test: `tests/test_a_branch_is_a_claim_that_expires.py`

**Contracts:** claim CRUD round-trips; push of unclaimed new branch FAILS naming it (fixture remote); claimed passes; expired claim → sweep archives+records+deletes (fixture repo); absent-registry = loud note-pass for the GATE (infrastructure absence, phase-1.4 law) but the SWEEP never deletes on an unreadable registry (fail-closed for destruction); ratchet green with the new red-path entry, no baseline delta.

- [ ] Steps: failing tests → registry → gate → sweep → RED_PATH + gates.yml → green → ruff → wrapper commits (≤3 counted/commit, split as needed) → subjects: `feat(forge): a branch is a claim with an owner and an expiry - anonymous forks end` / `feat(gates): the push refuses a branch nobody owns`

### Task 3: The proof — history measured, fixes judged

**Files:**
- Create: `scripts/forge/sprawl_history.py` (read-only analyzer: branch-creation/deletion events from reflogs, the graveyard's 210+ branch deaths, refs/archive timestamps, server-ledger evidence already summarized in memory docs; emits a dated series: live-branch count + unpushed-commit estimate per week since 2026-05)
- Create: `plans/thomas/tasks/PRAXIS-BRANCH-EQUILIBRIUM/proof.md` (the curve as a table/ASCII chart; each prior intervention dated on the curve — advisory rules, janitor, squash ccea3027, custodian, the gates-not-enforcing window ending db808bdf, this cleanup — with the honest verdict per intervention: moved the number or didn't; state measurement limits plainly — reflog horizons, deleted-ref blind spots)
- Test: analyzer unit tests on a fixture repo (sentence-named)

**Contracts:** the analyzer never guesses — unknown windows are marked unknown; the proof doc's every number regenerable by the committed analyzer (command quoted in the doc); second person for owner text, no name.

- [ ] Steps: analyzer + tests → run against the real repo → write proof.md from real output → wrapper commits → subject: `feat(forge): the sprawl curve is measured - and every past fix gets its honest verdict`

### Task 4: Closure under the loop's law

**Files:**
- Modify: the Task-1 incident record (status resolved + `- closure: gate:branch_claim_gate.py` — legal only once the gate is RED_PATH-registered and enforcing in CI; run the closure gate's resolver by hand as proof)
- Create: `plans/thomas/tasks/PRAXIS-BRANCH-EQUILIBRIUM/status.md` (what enforces where; the TRUNK line quoted live; the going-forward counters and the one-month flatness criterion with the red condition stated: if sprawl regrows under enforcement, the model is wrong; the tap items queued: hook wiring if pinned, custodian adoption if pinned, gate promotion to local enforcement)
- Modify: `plans/thomas/tasks/PRAXIS-PHASE14-BREAKGLASS/batch.md` IF new tap items exist (clearly-marked section, STATUS PREPARED untouched)

- [ ] Steps: verify → close → docs → wrapper commit → subject: `docs(praxis): the fork stops being free - and the proof is a curve anyone can re-run`

## Self-review notes
- The mechanism attacks the equilibrium (landing cheap + loud, forking recorded + expiring), not the symptom; every enforcing piece carries a red-path test; the proof is measurement, not narrative.
- Destruction is uniformly fail-closed (sweep never acts on unreadable state); surfacing is uniformly fail-open-with-note (session start never breaks).
- The December-1 REOPEN convergence and this program's risks are unaffected; no pinned file is touched without a tap item.
