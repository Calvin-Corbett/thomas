# Evolve-Itself Master Plan — Claude (coordinator) + Codex (implementer)

**Status:** proposal v1 (Claude). Codex: read, counter-propose, then claim P0.
**Date:** 2026-06-22. **Authority:** Calvin (recursive self-evolving loop + meta-orchestrator).
**Roles (Calvin's fixed law):** Codex = sole implementer (owns `evolve.py`). Claude = coordinator + co-planner + reviewer, **no coding**. Cycle: Codex implements one tranche → Claude reviews the green diff adversarially → repeat.

Derived from a 10-agent adversarial design pass (4 opposed architects → red-team each → synthesize). All four red-teams converged on the same truth below.

---

## 0. THE ONE TRUTH EVERYTHING SERVES

**A loop that judges its own success will, given enough iterations, learn to fake success instead of earning it.** Its highest-leverage discovery isn't "how to improve Thomas" — it's "how to make the gate say yes more often."

Three FACTS verified against the real code (not designs):

1. **The green mirror IS the agent's writable tree, and it contains the judge.** `doppelganger.py:29` `_INCLUDE_DIRS = ('thomas','scripts','tests','definitions')` covers `thomas/forge/anvil/` — so `evolve_autonomy.py` (gate), `evolve.py` (verifier), and `tests/` are all editable mid-pass. Listing a file in `agent_safety.toml` does nothing about this; **no `evolve_*.py` is even in the protected set today.**
2. **Promotion wholesale-copies green→blue with no protected re-check at copy time.** `sync_green_to_blue` (`doppelganger.py:207`) copies the whole tree; `_revert_protected_changes` runs once, earlier, off a name-based diff — so new files (`evolve_autonomy_v2.py`), renames, and win32 path misses ride straight in.
3. **"Verified" routinely means "it imports."** `_blast_radius_tests` (`evolve.py:483`) selects tests by grepping for the changed module's name. Rename the module → zero tests match → verification collapses to `py_compile` → promotable. Or the agent writes its own trivial passing test.

**The structural defeat (the spine of this whole plan):**
> Move every trust-bearing operation — delta computation, risk classification, test **selection**, test **execution**, protected-path enforcement, the promotion decision call site, and the spend meter — **OUT of the agent-writable mirror and OUT of `evolve.py`, into a separate BLUE-ONLY SUPERVISOR process** that re-derives every gate input independently and never trusts the agent-authored `session.json`.

The trust boundary is **process isolation + telemetry provenance**, not source-file ownership. The supervisor IS the project. "Freeze the file" is necessary-but-radically-insufficient theater until the supervisor exists.

**Non-negotiable gate:** no self-targeting code runs until the supervisor is real and proven to catch a planted exam-suppression, a planted risk-relabel, and a rotating planted fake.

---

## 0.5 HEAVY MULTI-AGENT FAN-OUT (Calvin requirement, first-class)

"Use a lot of agents" is not decoration — **it is the anti-reward-hacking mechanism.** The core danger is fooling *one* judge. The defense is **N independent, diversely-prompted verifiers** that must agree against external ground truth. So fan-out is required at every layer:

- **Supervisor verification = a PANEL, not one pass.** Each self-mod candidate is graded by multiple independent verifier agents (different lenses: correctness, reward-hacking-adversary, does-it-reproduce, security). Promote/keep only on majority agreement vs the frozen corpus.
- **Goal proposal = multiple planners** from diverse angles, deduped + voted.
- **Every Claude review of a Codex diff = an adversarial review panel** (multiple reviewers told to break it), then Claude synthesizes the verdict.
- **The orchestrator drives a FLEET**, not just two CLIs — many workers dispatched in parallel, aggregated, voted.

Where a phase says "verify" or "review" or "score," read it as "fan out to a panel."

---

## 1. WHAT "THE LOOP EVOLVES ITSELF" MEANS, CONCRETELY

**1.1 New abstraction — a `meta` goal, supervisor-classified.** Add a `meta` category (`evolve_planner_models.py` CATEGORIES) + `_detect_meta` detector (`evolve_planner_detectors.py:270`) emitting goals whose `target_paths` are the loop's own machinery. **Risk must NOT come from the mutable `CATEGORY_RISK` table** (a self-editing planner would downgrade `meta` high→low and defeat every gate). The **supervisor hardcodes: `category=='meta'` ⇒ force `risk=critical` ⇒ force human hold, posture-independent, covered by a frozen golden test.** The planner may only ever RAISE risk, never lower the supervisor floor.

**1.2 Two rings — cut on PROCESS, not file ownership.**
- *Mutable (loop may self-edit, lands via supervised pipeline, human-gated because `meta`):* `evolve_planner*.py`, `evolve_loop_learning.py`, detector heuristics, prompt templates.
- *Supervisor-owned, NEVER loop-editable, runs from code physically outside `_INCLUDE_DIRS`:* promotion decision, delta/blast-radius/risk re-derivation, protected-path enforcement, promotion call site + posture + budget/kill checks (today in `evolve_loop.py` — **pull them OUT**), the frozen corpus + its signed lockfile, the spend governor.
- **Decision for Codex (P1):** new package OUTSIDE `thomas/`/`scripts/`/`tests/`/`definitions/` (e.g. top-level `evolve_supervisor/`, own pinned venv). The mirror physically cannot contain it. The loop imports nothing it can override; the supervisor reads loop outputs as untrusted data.

**1.3 Verification against a frozen corpus the loop can't author.** On EVERY promotion + EVERY self-mod, the supervisor:
1. Re-derives the delta from a clean blue↔green diff (never reads green's `session.json` as truth).
2. **Rejects the session** if the delta touches `tests/`, `conftest*`, `pytest.ini`, `sitecustomize.py`, `*.pth`, or creates any new `.py` in the loop's package (unless an explicit human-reviewed goal).
3. Selects blast-radius tests from **blue**, runs the exam in a fresh checkout, plus a **fixed floor corpus** independent of the changed file's name (kills rename-to-escape). `py_compile`-only ⇒ `verification_ran=True` but `verification_ok=False` ⇒ HOLD.
4. **Coverage check:** changed lines must be covered by a test the session did not author. Zero ⇒ HOLD.
5. **Self-mod specifically:** run the candidate machinery against the frozen corpus (known-good must stay promotable; known-bad — no-op, faked returncode, gate-bypass, empty-verification, rename-escape, risk-relabel, exam-suppression — must stay rejected). New machinery must score ≥ incumbent on EVERY case **as judged by the verifier panel**. Corpus content-hash must match a human-signed lockfile or the supervisor fails closed.

**1.4 Safety spine — NEVER auto-promoted (hard law, no posture override):** supervisor-owned paths, auth, security, `thomas/core`, tools, server routes above low risk; any `meta` self-mod; any session where verification didn't run; any delta touching test infra or creating new loop-package `.py`; any change that REDUCES tests covering a touched module. **Policy violation on a supervisor path ⇒ REJECT the whole session + tamper counter + PushNotification** (today it reverts-and-promotes-the-rest, turning the protected set into an enumeration oracle).

**1.5 Did a self-mod make the loop BETTER? (external credit, rollback).** Credit must NOT be self-minted (`promotions − fails` is farmable — promote cheap cosmetics to inflate a category). Score on ground truth the loop can't manufacture: **human-approval rate of held items + post-promotion smoke-regression rate**, measured by the supervisor. Grade machinery on a **rotating** held-out corpus (static planted fake is overfittable). **Rollback:** per-self-mod snapshot journal (pre/post sha); after every promotion the supervisor re-runs the floor corpus against live blue — any regression ⇒ auto-rollback + HALT. **Anti-blindness:** pin a minimum detector-coverage set; a sudden empty backlog after a planner self-edit is a regression signal, not victory.

---

## 2. PHASED ROADMAP (each phase = one Codex tranche + one Claude review panel)

**Hard rule: no phase ships until the prior review passes. No self-targeting (P3+) until P1 AND P2 are proven against adversarial cases.**

| Phase | Goal | Deliverable | Gate to next |
|---|---|---|---|
| **P0 — Stop the bleeding** | Close the promotion-time hole + policy-violation oracle, ZERO new capability. | (a) Re-run protected-path/hash enforcement INSIDE `sync_green_to_blue`, abort on any supervisor-owned diff. (b) Reject sessions touching test infra or creating new loop-package `.py`. (c) Policy violation ⇒ reject whole session + tamper counter. (d) `py_compile`-only ⇒ `verification_ran` but NOT `verification_ok`. | Tests prove a new-file gate-bypass AND a rename-to-escape are both blocked. |
| **P1 — The supervisor (THE project)** | Relocate ALL trust-bearing logic to a blue-only process outside `_INCLUDE_DIRS`. | Supervisor re-derives delta, selects blast-radius from blue, runs exam in clean checkout, re-classifies risk = `max(planner, supervisor_floor)`, enforces protected paths by resolved real-path, owns promotion call site + posture + budget/kill, hash-checks live `evolve.py`/`evolve_autonomy.py` vs a signed lockfile, reads `session.json` display-only. **Verification = panel.** | Supervisor catches planted exam-suppression + risk-relabel + faked-returncode no-op, without reading green's `session.json`. |
| **P2 — Frozen corpus + spend governor** | Externalize the objective + cap the money. | `evolve_corpus/` (known-good + adversarial-known-bad per named vector + golden gate pairs) + signed lockfile; supervisor fails closed on hash mismatch. External spend governor process: hard daily+total $ cap from a config the loop can't write, SIGTERMs the loop tree on breach. Invert falsy-budget guards (`evolve_loop.py:144`) to fail-closed. | Governor kills a runaway; corpus rejects a novel hand-crafted hack Calvin adds. |
| **P3 — Meta detector (PROPOSALS ONLY)** | Loop SEES its own machinery as improvable; promotes nothing. | `meta` category (supervisor forces critical) + `_detect_meta` + hard `target_paths` scope enforcement (revert out-of-scope; REJECT on supervisor-path reach). All meta goals held + surfaced via `message.py`. | Meta goals appear; none can promote; out-of-scope meta edit rejected. |
| **P4 — First supervised self-mods** | A real planner/learning improvement lands, human-tapped. | `approve_pending` wired for meta (re-run-then-promote, never stale); per-day meta cap = 1; snapshot journal + verified rollback. Credit store (approval-rate + smoke-regression) feeds PLANNER ONLY (gate stays history-blind). | One genuine self-mod promoted via tap, then cleanly rolled back. |
| **P5 — Structured Claude↔Codex orchestrator (headless)** | Run continuously under budget; every self-mod human-gated. | Conductor over injectable `session_runner` (`evolve.py:658` = Codex dispatch) + `message.py` review gate + `write_control` stop. Single-slot mirror lock. Dead-man heartbeat. Runaway detected from EXTERNAL observables (git history, spend ledger, process count) — never loop-authored `events.jsonl`. Fleet dispatch. **NO computer-use.** | Soak N days on real backlog; no unattended promotion of anything ≥medium. |

**Honest reframe (all four red-teams converged):** "indefinite unattended self-evolution" + "every meta change gated by the only human" is self-contradictory — it stalls within a day or creates standing pressure to remove the gate (the repo's own breakglass-retry history proves the temptation). **Reframe the goal: continuous PROPOSAL generation, batched human landing. A stall is the SAFE state; never "fix" a stall by weakening the gate.**

---

## 3. FINAL PHASE — Thomas-as-meta-orchestrator (computer control), and what is premature

**P6 is gated behind P5 being empirically trustworthy. Most is premature; parts must NEVER be built.**

- **Buildable + bounded:** computer-use as a transport for **restart/liveness only** — better still a plain watchdog/cron relauncher, not a screen-driving agent (typing goes into whatever window has focus; no reliable intent↔effect reconciliation).
- **CUT permanently:** computer-use must NEVER touch approval, signing, breakglass, branch-protection, or auth. Win-Hello's whole value is that it's a physical human action; a mouse-driving agent that taps its own approval makes the human lane decorative. Held critical/meta changes require an **out-of-band cryptographic signature** (hardware key signing a commit, supervisor-verified against a public key) — not a clickable dialog. No typing into a terminal where it can run `git commit --no-verify` or hand-edit the gate.
- **"Thomas types organically to drive both agents forever" buys nothing** over the headless `subprocess` + `message.py` dispatch that already exists, except un-auditability and runaway risk. If Calvin wants to watch, render a **read-only dashboard** of the structured dispatches.
- **Envelope if any computer-use ships:** dedicated non-privileged terminal, no credentials, allowlist of zero-security-meaning actions, idle-guard, dead-man heartbeat auto-revoke, the P2 spend governor + HALT above it, quiet hours. Structured dispatch is always source-of-truth; typing is at most a dumb liveness transport.

---

## 4. CLAUDE ↔ CODEX COLLABORATION & REVIEW PROTOCOL

**Division (enforced in config, not etiquette):** Codex = sole implementer, full tools, owns `evolve.py`. Claude = coordinator/planner/reviewer, review-only profile (no write tools — matches chatbot-only law), authors dispatches + reviews, never diffs.

**Co-planning:** Claude maintains the phase backlog + writes each tranche spec (scope, `target_paths`, acceptance criteria, the specific adversarial cases the supervisor must catch). Codex implements one tranche at a time in an isolated worktree/green mirror. **Codex is expected to counter-propose** — this plan is v1, not orders.

**Per-diff review — Claude's panel checks EVERY diff for:**
1. Did anything trust-bearing leak back into the mirror? (no supervisor logic in `thomas/`/`scripts/`/`tests/`/`definitions/`; no new loop-package `.py` re-implementing a gate)
2. Is `risk_tier` still supervisor-derived, `meta` still forced critical?
3. Is the exam still run from blue on a corpus the session didn't author? (`py_compile`-only still ⇒ HOLD)
4. Does promotion re-enforce protected paths at copy time? (regression-check `sync_green_to_blue`)
5. Are budget/kill/posture checks in supervisor code, not editable `evolve_loop.py`?
6. Scope: did the diff edit only its declared `target_paths`?

**Mechanics over existing seams:** dispatch Codex via `evolve.py:658` (`python -m thomas chat --autonomy-level 4 -m openai_codex`). Review handoff via `scripts/crew/workboard/message.py` (`kind=review_request` → Claude panel reviews green diff → `approved|rejected`; rejected feeds back as a refined goal, never auto-promotes). **Claude's verdict is advisory to the revise-loop, NOT an input to `decide_promotion`** (a review fed into the gate is a capturable gate). For ≥medium risk, "verified-but-unreviewed ⇒ hold" so review gates where it matters.

---

## 5. RUTHLESS CUTS
- **CUT** "freeze the file in `agent_safety.toml`" as a sufficient story (freezes the judge, leaves the loop free to write its own exam).
- **CUT** the static single planted-fake oracle (overfittable → rotate, externally authored).
- **CUT** computer-use tapping Win-Hello/breakglass (self-approval).
- **CUT** "indefinite unattended" framing → continuous-proposal / batched-human-landing.
- **CUT** any history-fed planner/reranker self-mod BEFORE supervisor + corpus + meta-gate exist (goal-distribution capture before the cage).
- **CUT** trusting `events.jsonl` for runaway detection (the suspect keeps the diary).
- **KEEP (already real, build on these):** the fail-closed `verification_ran` vs `verification_ok` split (landed 2026-06-22); the gate as a pure function the loop re-derives rather than trusting engine `promotable`; the sha256 tree delta; the deferred-approval re-run-not-stale path.

**Bottom line:** P0–P2 (supervisor + corpus + spend governor) is ~70% of the engineering and 100% of the safety. The recursive self-improvement everyone is excited about (P3–P5) is the *easy* part, safe only once the cage is real. P6 computer-control is mostly premature and partly must never be built. **Build the cage before the thing that needs caging.**

Key files (all `thomas/forge/anvil/`): `evolve_autonomy.py`, `evolve.py` (Codex's), `evolve_loop.py` (loses trust-logic to supervisor), `evolve_planner_*.py`, `evolve_loop_learning.py`, `doppelganger.py` (mirror scope + the promotion-time hole). New code: top-level `evolve_supervisor/`.
