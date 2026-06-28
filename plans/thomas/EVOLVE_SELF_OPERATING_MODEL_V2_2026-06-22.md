# Thomas Self-Evolution Operating Model v2

Status: Codex operating model, 2026-06-22.
Scope: Thomas evolve loop, blue-only supervisor, Claude/Codex review lane, and future meta-evolution.
Supersedes: not a replacement for `EVOLVE_SELF_MASTER_PLAN_2026-06-22.md`; this is the current executable operating model after the P0/P1 work and the message-lane audit.

## Research Grounding

The strongest outside evidence points in the same direction as the local red-team plan:

- Self-improving coding agents can work when they edit their own scaffolding and are judged by concrete software tasks. The SICA paper reports self-editing agent gains on SWE-Bench Verified, LiveCodeBench, and synthetic benchmarks, with the key caveat that the evaluator must be meaningful and protected.
- AlphaEvolve shows the productive pattern for open-ended code improvement: many candidate programs, automated evaluators, evolutionary selection, and verified improvement on objective functions.
- SWE-agent shows that the agent-computer interface matters. Tool shape, file navigation, edit ergonomics, and test execution are not incidental; they are part of the intelligence of the loop.
- Reflexion shows useful learning can happen through structured verbal feedback and memory without weight updates, but the feedback source must be external enough to avoid self-flattery.
- METR's reward-hacking evidence is the failure mode to assume by default: capable agents exploit tests, scoring code, leaked answers, and environment loopholes when the metric is easier to hack than the task.
- Parallax-style separation is the right security pattern: reasoning and execution cannot live at the same trust level, validation must be independent, and rollback has to be built in.

Sources to re-check when this model is revised:

- SICA: https://arxiv.org/html/2504.15228v1
- AlphaEvolve: https://arxiv.org/abs/2506.13131
- SWE-agent: https://arxiv.org/abs/2405.15793
- Reflexion: https://arxiv.org/abs/2303.11366
- METR reward hacking: https://metr.org/blog/2025-06-05-recent-reward-hacking/
- Parallax: https://arxiv.org/html/2604.12986v1

## Core Law

Thomas may optimize itself indefinitely only if the objective, judge, budget, and promotion authority are outside the code the evolving agent can edit.

The loop is not "reach the goal and stop." The goal is a moving frontier:

1. Improve Thomas on externally measured user outcomes.
2. Preserve safety and reliability invariants.
3. Expand into new domains only through measurable capability contracts.
4. Treat every successful self-change as a new hypothesis that must survive future regression, adversarial review, and rollback tests.

Stall is allowed. A weakened gate is not.

## Current Live State

Built or partially built:

- `evolve_supervisor/` exists outside the green mirror's main mutable package path and re-derives candidate deltas without importing `thomas` or `scripts`.
- `evolve_supervisor.decision` owns the promotion decision matrix and keeps `verification_ran` separate from `verification_ok`.
- `thomas/forge/anvil/evolve.py` promotes through `_promote_verified_green_delta`, which evaluates a blue-derived candidate through `evolve_supervisor.evaluate_candidate`.
- Green evolve now has read-only `code.search` and `fs.search` for context discovery while git inspection and commit tools remain denied.
- `diff.create` handles numbered `fs.read_file` snippets only when the stripped old text uniquely matches.
- Targeted explicit-goal evolve runs skip hidden refactor-first work by default; refactor-first remains for refactor-category planning.
- `scripts/crew/workboard/message.py --audit` now detects parse errors and noncanonical Claude/Codex notes that inbox/current views would otherwise miss.
- `scripts/crew/brief/startup_router.py` surfaces `message_audit`, `inbox`, and `current_thread` so agent startup has a deterministic communication diagnosis.
- `evolve_corpus/` now exists with `LOCK.json`, and `evolve_supervisor.evaluate_candidate` fails closed when the blue-owned corpus is missing, modified, or contains unlocked files.
- `evolve_governor.toml` now exists at repo root, and `evolve_supervisor.evaluate_spend_governor` checks the root spend ledger before each `run_evolve_loop` dispatch.
- `agent_safety.toml` now protects `evolve_governor.toml` and `evolve_corpus/LOCK.json` from casual agent edits.

Known missing pieces:

- No executable frozen-corpus runner yet; P2a currently enforces corpus integrity, not full corpus grading.
- No independent verifier panel yet; current verification is still local command execution plus supervisor checks.
- No out-of-process spend watchdog that can terminate an already-running child process; P2b currently stops before dispatching another green session.
- No meta category/detector path that lets Thomas propose loop improvements without promoting them.
- No per-self-mod rollback journal that automatically reverts a regression after live promotion.
- No cryptographic human approval path for critical/meta changes.
- No read-only dashboard for the long-running conductor state.

## The Fancy Loop

Each cycle is a closed control loop with explicit gates:

1. Intent intake
   - Convert user asks, telemetry, failures, stale docs, and Claude review notes into goal cards.
   - Every goal card has: objective, target domain, target paths, measurable success, risk floor, expected tests, rollback condition, and owner.
   - Goals are never accepted if they only improve an internal proxy with no user-facing or reliability-facing measurement.

2. Portfolio selection
   - Maintain a backlog across domains: reliability, UX, agent capability, tool ergonomics, memory, marketplace, security, performance, docs, and meta.
   - Select work by expected value, risk, age, and learning diversity.
   - Prevent single-domain obsession by quotas and rotating challenge sets.

3. Blue preflight
   - Resolve communication state with `message.py --audit`.
   - Check worktree, active claims, protected paths, budget, and current Claude thread.
   - Refuse to start if the supervisor package, safety config, or frozen corpus is missing or modified unexpectedly.

4. Multi-agent proposal fan-out
   - Planner panel proposes several candidate approaches.
   - Red-team panel tries to identify reward-hacking paths before coding starts.
   - Coordinator synthesizes one bounded candidate goal.
   - Codex may counter-propose if scope is too broad, not measurable, or unsafe.

5. Green execution
   - Candidate runs only in the green mirror.
   - It can search/read/edit allowed target code and run verification.
   - It cannot inspect git state, commit, edit supervisor-owned paths, author its own exam, or weaken gate inputs.
   - A failed edit must be followed by a corrected edit or explicit no-change refusal, not fake verification.

6. Supervisor re-derivation
   - Supervisor ignores agent-authored truth claims.
   - It re-derives the delta from blue/green filesystem state.
   - It enforces protected paths, test infrastructure bans, loop-package bans, and supervisor-package bans.
   - It computes the risk floor. `meta` must force critical.

7. Verification panel
   - Run generated tests only as supporting evidence.
   - Run a fixed floor corpus independent of changed-file names.
   - Run blast-radius tests selected from blue, not green.
   - Run adversarial known-bad cases: no-op, empty verification, renamed target, faked return code, test suppression, risk relabel, leaked answer, and malformed communication.
   - Require at least one non-agent-authored verification signal for promotion. `py_compile` alone can prove syntax but cannot prove fitness.

8. Promotion decision
   - Low/medium clean changes may promote only under the configured posture.
   - High/critical/meta changes hold for human approval.
   - Any policy violation rejects the whole session, not "promote the rest."
   - Missing verification holds or rejects according to risk; it never auto-promotes.

9. Post-promotion audit
   - Re-run the floor corpus after promotion.
   - Write a rollback journal with pre/post hashes, changed files, verification evidence, and decision reason.
   - If the floor regresses, auto-rollback and halt the loop.

10. Learning update
   - Store lessons as externally grounded evidence: approval rate, post-promotion regression rate, user-visible outcome, test stability, cost, time, and reviewer objections.
   - Feed learning to planners and rankers, not directly to the gate.
   - Treat an empty backlog after planner changes as suspicious, not success.

11. Communication closeout
   - Replace the current Claude handoff with one canonical `message.py --send --replace-open` row.
   - Include audit counts, gates, changed files, and the exact red-team ask.
   - Never rely on free-text notes as coordination state.

## Meta-Evolution Rule

Thomas may eventually improve its own evolve machinery, but only as proposals until the following are all true:

- Frozen corpus exists and is hash-locked.
- Verifier panel exists.
- External spend governor exists.
- Supervisor rejects every planted meta-bypass.
- Rollback journal is proven with a live rollback test.
- Claude/Codex review lane is canonical and audited.

Until then, meta work can improve support code around the loop only when it is manually implemented by Codex, reviewed by Claude, and verified by the supervisor.

## Next Tranches

P2a: Frozen corpus and lockfile
- Status: initial lock enforcement landed.
- `evolve_corpus/` exists outside green-write authority.
- Known-good and known-bad seed fixtures exist.
- `LOCK.json` records content hashes.
- Supervisor fails closed on missing corpus, missing lockfile, hash mismatch, or unlisted corpus file.

P2b: External spend governor
- Status: initial pre-dispatch governor and runtime watchdog landed.
- Hard daily and total caps live in root `evolve_governor.toml`, outside green promotion scope.
- `evolve_supervisor.spend_governor` reads `thomas_spend.jsonl` without importing mutable loop code.
- `run_evolve_loop` stops before dispatch when projected spend exceeds the cap.
- Green agent subprocesses carry `THOMAS_EVOLVE_SPEND_WATCHDOG_ROOT`, so the blue-side watchdog can terminate
  already-running child process trees if the ledger breaches cap mid-session.
- Verification subprocesses strip the watchdog and spend env because they should not consume LLM budget.
- Malformed enabled config or malformed spend ledger fails closed.
- `evolve_governor.toml` and `evolve_corpus/LOCK.json` are protected in `agent_safety.toml`.
- Remaining work: executable corpus runner and verifier-panel quorum.

P2c: Executable corpus and verifier panel interface
- Status: initial executable corpus runner landed.
- `evolve_supervisor.run_evolve_corpus()` loads only locked case files and fails closed on lock errors.
- Session-shape cases execute through the blue-owned decision gate.
- Candidate cases synthesize temporary blue/green trees and execute through `evaluate_candidate()`.
- The runner currently covers clean verified sessions, empty verification, exam suppression, and meta risk relabeling.
- Define verifier roles: correctness, regression, security, reward-hack, reproducibility.
- Run verifiers against the same candidate bundle.
- Record disagreements, not just pass/fail.
- Promotion requires quorum plus no critical dissent.

P3: Meta detector, proposals only
- Add `meta` goal category and detector.
- Supervisor forces critical risk.
- Meta candidates can be generated and reviewed, but not auto-promoted.

P4: Approval and rollback
- Wire approve-pending for meta so it re-runs fresh, never promotes stale sessions.
- Add one-change-per-day meta cap.
- Prove rollback on an intentionally reverted safe change.

P5: Headless conductor
- Orchestrate Codex implementation and Claude review with structured `message.py` handoffs.
- Keep the dashboard read-only.
- Avoid computer-use for approval or security surfaces.

## Commands

Current communication diagnosis:

```powershell
python scripts\crew\workboard\message.py --audit --agent codex --peer claude --task-id evolve-self-p0-2026-06-22 --json
```

Current Claude thread:

```powershell
python scripts\crew\workboard\message.py --current --agent codex --peer claude --task-id evolve-self-p0-2026-06-22 --json
```

Focused communication gate:

```powershell
python -m pytest tests\test_workboard_message_script.py tests\test_agent_startup_router.py tests\test_workboard_inbox_gate.py -q
```

Supervisor gate:

```powershell
python -m pytest tests\test_evolve_supervisor.py tests\test_evolve_autonomy.py tests\test_evolve_blast_radius.py tests\test_cli_evolve_commands.py -q
```

## Non-Negotiables

- The evolving agent never edits its judge.
- The judge never trusts agent-authored session truth.
- The exam is never only tests the candidate authored.
- The budget cannot be edited by the candidate.
- The review lane is canonical rows, not prose.
- A stalled loop is safe; a gate weakened to avoid stalling is a failure.
