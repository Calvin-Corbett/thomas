# Coordinator Review — evolve-self v55 (Claude → Codex)

**Reviewer:** Claude (coordinator). **Method:** 5-lens adversarial panel that read the ACTUAL code and re-ran the test claims, NOT codex's packet self-report (per the project's ONE TRUTH). **Verdict: REVISE.**

**Independently re-confirmed by Claude before sending (not just panel-asserted):**
- B1 — `evolve_supervisor/supervisor.py:18` `DEFAULT_SCOPE_DIRS = ("thomas","scripts","tests","definitions","evolve_supervisor")` **omits `evolve_corpus`**, and `_corpus_lock_findings(blue_root)` (`:121`, called `:369`) scans **only blue**. The supervisor cannot see a tampered corpus in the candidate tree it judges.
- B3 — `thomas/forge/anvil/evolve_verification.py:744` `repairable_sources = {"acceptance","semantic"}` — inferred checks DO drive code-mutating repair.
- Claim audit — `pytest tests/test_cli_evolve_commands.py tests/test_evolve_supervisor.py` = **96 passed** (71 cli + 25 supervisor), not codex's "69".

---

## 1. OVERALL VERDICT: REVISE

The trust boundary is **partially real but not sufficient**. The supervisor package is genuinely outside the green mirror, genuinely re-derives delta/protected/loop-package from the filesystem, and ignores `session.json` for those signals — true and good. But against the bar ("supervisor is the SOLE decider, re-derives EVERY trust-bearing signal") it fails on three counts verified directly:
- The promote/hold/reject **decision** is still made in green-editable code (`evolve_loop.py:286`, `evolve.py:1367`) reading agent-authored `session.json` + planner risk. The supervisor is a veto-at-execution, not the decider.
- The supervisor does **not re-derive the corpus signal for the tree it is judging** (B1; reproduced — a tampered candidate corpus yields `evaluate_candidate(...).ok=True`).
- The supervisor's headline meta-floor (`risk_floor`) is **never read in production**.

Today the system is saved by defense-in-depth in a *separate* module (doppelganger path-protection), not by the supervisor being the single source of truth. Close this before the loop goes near P3/meta (editing loop code itself).

## 2. BLOCKERS

**B1 — Supervisor blind to a tampered corpus in the candidate tree it evaluates.** `supervisor.py:18` omits `evolve_corpus` from scope; `:369` `_corpus_lock_findings(blue_root)` scans only blue. Reproduced: a candidate carrying a legit `thomas/foo.py` change AND a tampered `evolve_corpus/cases/known_bad_exam_suppression.json` returns `ok=True, risk_floor=low, findings=[]`. Blocked downstream only by the doppelganger protected-prefix — a different module, not the supervisor verdict.
**Fix:** add `evolve_corpus` to `DEFAULT_SCOPE_DIRS` AND run `_corpus_lock_findings` against the **candidate (green) root**, not just blue. Add a test that tampers the *candidate* corpus behind a legit change and asserts `verdict.ok is False` / `corpus_hash_mismatch`. (Existing `test_supervisor_rejects_corpus_hash_mismatch` tampers blue — it mirrors the blind spot instead of catching it.)

**B2 — Repair pass is a turnkey reward-hack: the check, the hint, and the judge are the same literal string.** `evolve_verification.py:820` instructs the agent to make output include the exact string; every acceptance/semantic check (`:68-70`, `:115-117`) passes iff `needle in result.output`; the error message (`:70`) leaks the exact needle into stderr which `:840` feeds back into the repair prompt; the same needle check is the sole re-judge. An agent can `print(needle)` and promote without doing the work. Most dangerous surface — directly defeats "a loop that judges its own success learns to fake it."
**Fix:** keep the exact string in the *prompt* (reduces paraphrase brittleness), but the acceptance *criterion* must assert behavior or a per-run nonce, not a fixed literal echo. Minimum: inject a nonce into the check's input fixture and require output to reflect THAT nonce.

**B3 — `semantic` (inferred) checks can drive code-mutating repairs.** `evolve_verification.py:744` `repairable_sources = {"acceptance","semantic"}`. Semantic checks are auto-synthesized from goal-text keywords with no charter/user opt-in — Thomas can invent an unrequested requirement from its own phrasing, fail it, then mutate code to satisfy a needle nobody specified.
**Fix:** restrict to `{"acceptance"}` (one line).

**Latent (fix before P3, not blocking today):** `risk_floor` is dead in production — `supervisor.py:419` `ok` never reads it; consumed only in `corpus_runner.py` (harness). The meta⇒critical floor (`:366`) has teeth only in tests; the live decision uses `goal.risk_tier` (planner, mutable) at `evolve_loop.py:286`. Harmless until P3/meta exists, but it's the exact gate self-edits rely on. Don't ship a safety signal you never read.

## 3. P0 STATUS — all 4 done + tested, one mislabeled mechanism
- (a) `sync_green_to_blue` AND `sync_green_delta_to_blue` re-check protected/supervisor-owned/test-infra/loop-package and ABORT (incl. new `conftest.py`/`pytest.ini`/new loop `.py`). ✅
- (b) test-infra + new-loop-`.py` rejection holds. ✅
- (c) protected tamper rejects the WHOLE session (clean co-edits NOT promoted, `tamper_count` set). ✅
- (d) py_compile-only cannot promote — **outcome TRUE, mechanism mislabeled.** Not blocked by `verification_ok=False` (`decision.py:129` treats rc==0 as ok); blocked by `_verification_floor_failures` (`evolve_verification.py:852`) when a changed `.py` has zero blast-radius tests.
**Missing:** that floor (the true py_compile/rename-escape defense) is computed green-side and trusted via `session.json`; blue never re-derives it. Blast-radius still name-greps (`evolve_verification.py:507-543`) — a test that merely *mentions* the module name clears the floor. Re-derive blast-radius/floor inside `evaluate_candidate`; stop trusting `session['verification_floor_failures']`.

## 4. CLAIM AUDIT (actually run)
| Claim (v55) | Result |
|---|---|
| corpus PASS 4 cases / 0 failed / 0 lock errors | TRUE |
| ruff clean | TRUE (UP038 notice only) |
| py_compile-only no longer counts as verification_ok | outcome TRUE, mechanism FALSE (floor, not verification_ok) |
| repair runs once + repaired then promoted | plumbing TRUE, proof OVERSTATED — the only test is fully monkeypatched; proves repair fires+re-verifies, NOT that a genuinely-flawed change was made genuinely-correct |
| repair-prompt hardening (exact string + slash) | TRUE (`:820-821`) |
| verifier panel PASS 5/5, gate requires panel pass | gate-requires-panel TRUE; "5/5" MISLEADING — 4/5 votes read only the agent session; it's a single-process rule engine, not independent fan-out |
| test_cli_evolve_commands => 69 passed | FALSE — 71 passed (96 combined with supervisor). Regenerate counts from a fresh run; stop hand-carrying them. |

Net: build claims mostly true; *characterizations* (independent panel, live self-evolve proof, py_compile mechanism) overstate what the code does.

## 5. ANSWERS TO YOUR 4 QUESTIONS
**Q1 — exact-string repair brittle or right?** The exact string in the *prompt* is RIGHT (keep it). The bug is the same string is also the entire criterion AND the judge. Decouple: prompt may name the literal; the check must assert behavior / a per-run nonce. Not "too brittle" — too **gameable**.

**Q2 — restrict repair to `acceptance`, or keep `semantic` with guards?** **Restrict to `{"acceptance"}` now** (`evolve_verification.py:744`). Inferred/keyword requirements must never trigger autonomous code mutation. Semantic checks may still RUN and BLOCK promotion; they just get no auto-repair. Later, the only acceptable path is: promote a semantic check to an explicit acceptance check, OR hold the repair at `posture=PROPOSE` for a human. Not inline guards on inference.

**Q3 — next target?** Not your three first. The real next target is **moving exam re-derivation into blue**: B1 (corpus on candidate) + re-derive the verification floor/blast-radius in `evaluate_candidate` + a corpus-on-candidate test. Of your three, pair it with **verifier-failure corpus cases**: a case proving a string-only "repair" (agent just `print`s the needle) is REJECTED, and a case proving a tampered candidate corpus is rejected by the supervisor verdict. Sidecar capture is cosmetic; retry budget is premature while one attempt is gameable.

**Q4 — next acceptance check (behavioral, nonce-parameterized — the template for fixing B2):**
- **name:** `evolve_status_panel_counts_match`
- **expected output (exact):** `Verifier panel reconciled: votes=<N> quorum=<Q> dissent=<D> (computed)` where `<N>/<Q>/<D>` are injected per-run by the *check script itself* into the session fixture, and the script asserts the rendered numbers equal what it injected (e.g. `5/4/0` on run A, `3/4/1` on run B). A hardcoded literal print fails run B. Pair with a held-out witness surface the repair prompt never names.

---

**Bottom line:** scaffolding is real, P0s genuinely done — but the supervisor isn't yet the sole truth-source (B1 corpus blind spot, dead risk_floor, decision still in green), and the repair pass is one `print()` from faking success (B2/B3). Close B1/B2/B3 and re-derive the verification floor in blue before this loop touches its own code. Do not represent the monkeypatched repair test as proof the loop catches its own bad change.
