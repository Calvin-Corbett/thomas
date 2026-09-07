# Phase 2 Repairs, Batch 2 (spec phase 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A small, sharp batch: the split debt one line from the cap is paid; two incidents whose problems no longer exist close under the loop's law; the ledger's oldest record stops accusing a healthy gate.

**Evidence basis:** batch-2 recon (scratchpad batch2-recon.md, verified at 858c8c98): the Surface parity gate passes cleanly offline today and the 40 failure records were two unlocked `auto_checks.py` processes double-appending through `problem_record.py` during a since-fixed failure window; runtime-protection-fix-2026-05-27 is fixed-by-obsolescence (`thomas/tools/filesystem.py:252-266` always-protects, 44/44 tests); claim_evidence.py is 799/800 with a zero-back-dependency seam mirroring the worker.py precedent.

**Owner-gated, excluded and queued:** agent-messaging-reliability-2026-06-02's missing status-field stamp (the mechanism it asks for is already built at HEAD — only the record's own bookkeeping decision remains); any edit to pinned `problem_record.py` (the unlocked-append double-fire fix is a future tap candidate).

**Spec:** `docs/superpowers/specs/2026-08-24-praxis-first-design.md` §2. Owner delegation 2026-08-24 active. All prior Global Constraints apply (wrapper commits, no double quotes, no manual trailers, CHANGELOG entry per commit regardless of the gate counter, fixture-only tests, pending working-tree items untouched, closure grammar is law).

---

### Task 1: claim_evidence pays its debt (move-only split)

**Files:**
- Create: `scripts/crew/workboard/claim_evidence_storage.py` (~296 lines per the recon seam: `Evidence`, `parse_evidence`, `format_evidence_field`, validators, `EvidenceRecord`, `record_evidence`, `read_evidence`, `strip_evidence`, task-line helpers)
- Modify: `scripts/crew/workboard/claim_evidence.py` (drops to ~502: `Verdict`, `verify_evidence`, binding/git helpers; imports + re-exports by assignment so all 7 call sites and every existing test are untouched)

**Behavior:** move-only, worker.py/worker_pipeline.py precedent exactly — token-identical moved code modulo imports, re-export-by-assignment, zero caller changes. While in the file, apply the ONE sanctioned rider from the T3 review: `_resolve_verify_target_branch` switches `rev-parse --verify` to `git show-ref --verify` (the nested-DWIM residual fix, "next touch" ruling) + one test from the reviewer's `refs/heads/refs/heads/dev` repro.

**Contracts:** full evidence suite + evidence-gate suite + reactivate/sweep suites green unchanged; the two adversarial ref tests green + the new nested-DWIM test; both files <800; AST/token move-verification stated in the report.

- [ ] Steps: split commit (move-only) → rider commit (show-ref + test) → suites → ruff → subjects: `refactor(crew): claim evidence splits its storage from its verdicts - one line of headroom was not enough` then `fix(crew): show-ref never guesses - the last ref trick dies`

### Task 2: Two incidents close because their problems are gone

**Files:**
- Modify: `plans/thomas/problems/runtime-protection-fix-2026-05-27/PROBLEM.md`, `plans/thomas/problems/audit-24h-backstop/PROBLEM.md` (both untracked/gitignored — surfacing enforces, the gate cannot see them; known and disclosed)
- Possibly: `docs/ops/accepted_risks.json` via the registry CLI (see B)

**Behavior:**
- **A. runtime-protection-fix-2026-05-27:** verify the recon's obsolescence finding fresh (filesystem.py:252-266 + run the 44 protection tests). Then find the closure: does a RED_PATH_CASES gate genuinely guard this incident's class (candidates: protected_files_gate.py — read what the incident actually asked for and judge coverage honestly)? If yes: status resolved + `- closure: gate:<that gate>`. If NO gate covers it (runtime code + tests is the guard, and tests are not a closure form): this is the closure-grammar gap's second instance — close under ONE new accepted risk (owner `calvin (standing delegation 2026-08-24, claude-recorded)`, reason naming the gap: fixed-and-permanently-tested incidents have no closure form; expiry 2026-11-30 so the vocabulary question resurfaces with the landed-scope risk), and record in the report that a `test:` closure form is a design candidate for the owner queue — do NOT build it.
- **B. audit-24h-backstop:** update the record body honestly: the parity gate passes today (quote the fresh run), the 40 records were the double-append mechanism (two unlocked processes, `problem_record.py` append, mechanism one-paragraph), the underlying complaints are stale. Then close: the double-fire's real fix is tap-gated (pinned file) — closure is `- closure: accepted-risk:<id>` under ONE new risk covering "problem_record.py's unlocked append can double-fire records until the file-lock lands via a tap" (expiry 2026-11-30). Both A-if-no-gate and B may share ONE risk ONLY if the reason honestly covers both — otherwise two records; implementer judges and states.
- Run `incident_surfacing` after: expect 15 open / 0 / 1 (two closures; quote the real lines). Run the closure gate's resolver on both files directly (file mode) and paste the resolution proof — the gate cannot see the diff, so prove the closures resolve by running the resolver by hand.

**Contracts:** closures RESOLVE (proven by execution); record bodies state what was verified, not what was assumed; no pinned files; the dirty audit-24h-backstop working-tree state from other sessions — read `git status` for it first; it is untracked so there is no staged conflict, but if another session holds it open with newer content than the recon described, re-verify before editing.

- [ ] Steps: fresh verification of both findings → closure decisions with evidence → registry record(s) via CLI → record edits → resolver proof + surfacing run → wrapper commit (registry json + CHANGELOG; the PROBLEM.mds are untracked): `fix(crew): two scars close because the wounds are gone - and the oldest record stops accusing a healthy gate`

### Task 3: Batch closure

**Files:**
- Modify: `plans/thomas/tasks/PRAXIS-PHASE2-BATCH1/status.md` (append a clearly-marked Batch 2 section rather than a new doc — one place for the phase-2 story)

**Behavior:** what landed with shas; the closure decisions and their reasoning (especially the grammar-gap instance if taken); the fresh surfacing lines; the owner queue GROWS by: the messaging status-field stamp decision, the `test:` closure-form design question (if hit), the problem_record.py file-lock tap candidate. Debts cleared: claim_evidence split done, nested-DWIM dead. Second person, no name.

- [ ] Steps: verify every claim → append → wrapper commit: `docs(phase2): batch two lands - small, sharp, and the ledger is fifteen`

## Self-review notes
- Everything here is instrument-ranked (recon-cited) and engineering-only; every owner decision is queued, none is made.
- The two closures are the loop working as designed: one likely ends in a practice (a covering gate), one ends in an owned expiring risk because its real fix is signature-gated — and both resurface via REOPEN DUE if the risks lapse.
