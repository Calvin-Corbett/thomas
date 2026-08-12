# Thomas-Native Self-Improvement Transfer Plan

> Reviewed: 2026-06-28 by thomas-self-improvement-native-transfer-optimizer. Scope: docs-only scouting of external `plans/thomas/evolve_auto/*` loop design and live Thomas surfaces for native transfer candidates.

## Purpose

The external `evolve_auto` / NIGHTSHIFT pipeline is a useful prototype, but it is still a Codex/Claude-driven loop: JavaScript agent fan-out, external worktree isolation, external morning reports, and human review around branches. Thomas already has enough native substrate to absorb the loop without creating a second orchestration stack:

- `thomas/forge/anvil/evolve_planner.py` and `evolve_planner_detectors.py` choose and rank improvement goals.
- `thomas/forge/anvil/evolve_loop.py`, `evolve_loop_state.py`, and `evolve_loop_learning.py` run bounded cycles, persist state/events, and avoid repeated tarpit goals.
- `thomas/forge/anvil/native_orchestration.py` plans in-process worker lanes, dedupes active workers, detects dirty conflicts, and surfaces stale/dead active-folder claims.
- `evolve_supervisor/decision.py` is the blue-owned promotion gate for pass/fail, human holds, and critical-risk floors.
- `thomas/marketplace/autonomy/*`, `thomas/server/routes/mission_control_routes.py`, and `thomas/notifications/api.py` already provide jobs, locks, audit, approvals, dashboard payloads, and notifications.
- `scripts/crew/workboard/*`, `scripts/active_folders.py`, and `scripts/crew/brief/commit.py` provide claim, lease, message, and commit discipline.

Native transfer should therefore mean: make Thomas own the loop's state, selection, dispatch, grading, dashboard, and cadence, while external agents become optional executors behind Thomas-owned contracts.

## Recommended Sequence

1. **Persist the loop as a first-class native program.** Extend the existing evolve/autonomy stores with self-improvement run/candidate/attempt records before adding more worker fan-out.
2. **Move selection and rubric generation into Thomas.** Use deterministic planner output plus an optional model ranker/rubric stage; never let the worker that writes the patch define the pass/fail contract after the fact.
3. **Dispatch through native orchestration and autonomy jobs.** Keep Codex/Claude as swappable executors, not coordinators.
4. **Grade through blue-owned gates.** Promote only from `evolve_supervisor` decisions plus recorded verification artifacts.
5. **Expose status in Mission Control and notify only on decisions/blockers.** Avoid heartbeat spam.
6. **Add cadence control last.** The cron/overnight loop should only run once state, dashboard, and grader contracts are durable.

## Transfer Candidates

### 1. Source Scouting Inside Thomas

- **What moves:** External seed-backlog mining and fresh-defect discovery.
- **Likely files:** `thomas/forge/anvil/evolve_planner.py`, `thomas/forge/anvil/evolve_planner_detectors.py`, `plans/thomas/THOMAS_CODEBASE_ISSUE_RANKINGS.md`, `plans/thomas/THOMAS_CODEBASE_ISSUE_QUEUE.md`, `scripts/crew/workboard/issue.py`.
- **Required data model:** `SelfImproveCandidate(id, source, title, rationale, target_paths, category, risk_tier, reproduction_hint, dedupe_fingerprint, priority, status)`.
- **Tests:** Unit-test candidate dedupe, ranking stability, focus bias, and "dirty/claimed path excluded" behavior with synthetic repo trees.
- **Security risks:** Prompt injection from repo docs/backlogs; selecting protected files; duplicate work against active claims.
- **Acceptance rubric:** Given a dirty repo with active claims and a ranked backlog, Thomas emits a deterministic candidate list that excludes claimed/protected scopes, records why each candidate was admitted/deferred, and can be rendered as JSON without model calls.

### 2. Rubric Generation

- **What moves:** NIGHTSHIFT's "done signal" and acceptance-check construction.
- **Likely files:** `thomas/forge/anvil/evolve_funnel_stages.py`, `thomas/forge/anvil/evolve_planner_models.py`, `thomas/forge/anvil/evolve_verification.py`, `evolve_corpus/cases/*`.
- **Required data model:** `AcceptanceRubric(candidate_id, required_checks, red_test_required, verification_commands, forbidden_paths, artifact_requirements, human_hold_rules, generated_by, generated_at)`.
- **Tests:** Fixture candidate -> rubric JSON; protected-path candidate requires human hold; missing verification command fails closed; model-ranker failure falls back to deterministic rubric.
- **Security risks:** Worker-defined rubber-stamp rubrics; model-generated commands that execute unsafe shell; insufficient coverage for non-Python/UI changes.
- **Acceptance rubric:** A candidate cannot start a worker until Thomas has persisted a rubric that includes required artifacts, protected-path rules, and at least one executable or explicitly human-held verification path.

### 3. Worker Dispatch

- **What moves:** JS `parallel(...agent(...))` fan-out and worker prompt construction.
- **Likely files:** `thomas/forge/anvil/native_orchestration.py`, `thomas/forge/anvil/evolve_loop_actions.py`, `thomas/marketplace/autonomy/engine.py`, `thomas/marketplace/autonomy/store.py`, `thomas/cli/commands/evolve.py`, `scripts/crew/workboard/worker.py`.
- **Required data model:** `SelfImproveWorker(worker_id, candidate_id, attempt_id, runner_kind, claim_scope, branch_name, status, dedupe_key, lease_id, started_at, updated_at, stop_reason)`.
- **Tests:** Existing `tests/test_native_orchestration.py` should be extended for self-improvement recipes; add autonomy handler tests for candidate -> worker job -> recorded result.
- **Security risks:** Unbounded worker fan-out, overlapping edits, executor prompt injection, accidental dev/main landing.
- **Acceptance rubric:** Starting a native self-improvement run creates at most one worker per admitted candidate, dedupes against live orchestration/workboard state, refuses broad dirty conflicts, and records the worker contract before executor launch.

### 4. Isolated Worktrees

- **What moves:** External "own isolated git worktree" rule.
- **Likely files:** `scripts/crew/worktree_ledger.py`, `scripts/crew/worktree_debt.py`, `scripts/active_folders.py`, `thomas/forge/anvil/evolve.py`, `thomas/forge/anvil/native_orchestration.py`.
- **Required data model:** `SelfImproveWorkspace(attempt_id, path, branch, base_sha, owner_worker_id, lease_id, dirty_state, archived_at, cleanup_status)`.
- **Tests:** Worktree create/reuse/archive; stale worktree lock requeue; branch name policy; no worktree rooted outside repo-approved directories.
- **Security risks:** Path traversal, orphaned dirty worktrees, stale branches, writing to the operator's live checkout.
- **Acceptance rubric:** Every write attempt has a workspace record, base SHA, branch, and active lease; stale/dead-owner workspaces are visible before new dispatch; live checkout remains read-only for worker edits.

### 5. Grader Execution

- **What moves:** Red -> green -> revert-check, full relevant suite, and "no self-grading."
- **Likely files:** `evolve_supervisor/decision.py`, `evolve_supervisor/verifier_panel.py`, `evolve_supervisor/coverage_floor.py`, `thomas/forge/anvil/evolve_verification.py`, `tests/test_evolve_blast_radius.py`, `tests/test_cli_evolve_commands.py`.
- **Required data model:** `GradeResult(attempt_id, rubric_id, verification_ran, verification_ok, red_result, green_result, revert_result, coverage_floor, supervisor_decision, artifacts, grader_version)`.
- **Tests:** Known-bad corpus cases for empty verification, skipped tests, non-Python deltas, changed supervisor files, and missing revert-check artifact.
- **Security risks:** Worker modifying grader/gates, fake-green tests, deleting assertions, laundering failures through skipped verification.
- **Acceptance rubric:** No attempt is `verified` unless blue-owned code records non-empty verification, required artifacts exist, and `decide_for_session` returns promote/approve rather than reject.

### 6. Pass/Fail Persistence

- **What moves:** NIGHTSHIFT ledger, learning file, report queue, tarpit history.
- **Likely files:** `thomas/forge/anvil/evolve_loop_state.py`, `thomas/forge/anvil/evolve_loop_learning.py`, `thomas/marketplace/autonomy/store.py`, `.thomas/evolve/loop/state.json`, `.thomas/evolve/loop/events.jsonl`.
- **Required data model:** Prefer SQLite in `AutonomyStore` for long-lived records: candidates, attempts, grade results, approval decisions, branch outcomes, and category track record. Keep JSONL event append for streaming/debug.
- **Tests:** Crash recovery from `running`; repeated failure moves to tarpit/parked; approval updates category score; audit chain catches tamper if integrity key is configured.
- **Security risks:** Editable score history, stale success claims, loss of failure evidence, duplicate attempts after crash.
- **Acceptance rubric:** A restarted Thomas process can reconstruct current run state, pending approvals, failed attempts, tarpit candidates, and the next due cadence without reading external thread history.

### 7. Notification Policy

- **What moves:** Morning report, phone push, inbox messages, and quiet heartbeat rule.
- **Likely files:** `thomas/notifications/api.py`, `thomas/notifications/dispatcher.py`, `scripts/crew/workboard/message.py`, `thomas/marketplace/autonomy/store.py`, `thomas/server/routes/mission_control_routes.py`.
- **Required data model:** `SelfImproveNotice(run_id, severity, reason, candidate_id, action_url, delivery_state, created_at, acknowledged_at)`.
- **Tests:** Notify on ready-for-review, human approval required, blocker, anomaly halt; no notification on ordinary heartbeat; SSE stream emits actionable notices.
- **Security risks:** Notification spam, leaking sensitive paths/diffs, unauthenticated action URLs, unacknowledged approval requests.
- **Acceptance rubric:** A quiet successful heartbeat writes state but sends no push; a human-only decision or blocker creates one notification and one workboard message with stable action links.

### 8. Self-Improvement Dashboard

- **What moves:** External report table and branch review queue into Mission Control/Evolution dashboard.
- **Likely files:** `thomas/server/routes/mission_control_routes.py`, `thomas/server/web/js/runtime/046_evolution_dashboard.js`, `tests/test_web_evolution_dashboard.py`, `tests/test_server_mission_control.py`.
- **Required data model:** Dashboard payload with `runs`, `candidates`, `attempts`, `workers`, `grade_results`, `pending_approvals`, `tarpits`, `cadence`, and `last_notice`.
- **Tests:** API contract test; dashboard JS loader test; payload includes ready/deferred/failed lanes; completed elapsed time freezes; stale workers are hidden or marked cleanup-needed.
- **Security risks:** Exposing internal diff paths without auth; action buttons that bypass owner approval; stale UI claiming work is live.
- **Acceptance rubric:** Mission Control shows active self-improvement runs, ready review branches, blockers, and pending approvals from Thomas-owned state with no dependency on external Codex threads.

### 9. Stale-Owner Detection

- **What moves:** Manual dead PID/stale lease inspection into the native loop preflight.
- **Likely files:** `scripts/active_folders.py`, `thomas/forge/anvil/native_orchestration.py`, `scripts/crew/brief/presence.py`, `tests/test_presence_monitor.py`, `tests/test_native_orchestration.py`.
- **Required data model:** Existing active-folder claim fields are enough for first pass: `agent_id`, `claim_id`, `paths`, `pid`, `hostname`, `expires_at`, `owner_alive`, `stale`, `dead_owner`, `needs_cleanup`.
- **Tests:** Dead local PID marks cleanup-needed; remote host does not false-kill; stale lease blocks dispatch; cleanup recommendation is surfaced in orchestration plan.
- **Security risks:** Killing or overriding a real human worker, spoofed PID/host, dispatching over stale-but-owned dirty files.
- **Acceptance rubric:** Before any worker dispatch, Thomas records stale/dead owner findings and either blocks dispatch or emits a coordinator handoff; it never silently ignores conflicting leases.

### 10. Autonomous Cadence Control

- **What moves:** Fixed cron plus self-scheduling override.
- **Likely files:** `thomas/marketplace/autonomy/scheduler.py`, `thomas/marketplace/autonomy/engine.py`, `thomas/marketplace/autonomy/store.py`, `thomas/forge/anvil/evolve_loop_state.py`, `thomas/cli/commands/evolve.py`.
- **Required data model:** `SelfImproveCadence(schedule, quiet_hours, max_daily_cycles, max_tokens_or_cost, pause_until, last_run_at, next_run_at, halt_reason, consecutive_failures)`.
- **Tests:** Pause sentinel/control file halts next run; consecutive anomalies halt cadence; owner-active/dirty-conflict causes triage-only; recurring job survives a failed cycle and reschedules safely.
- **Security risks:** Cost runaway, repeated failing cycles, unattended branch sprawl, running while Calvin is actively editing.
- **Acceptance rubric:** With cadence enabled, Thomas can run one bounded cycle, reschedule itself, pause from dashboard/control file, and halt after anomaly thresholds without external automation owning the loop.

## Non-Goals For The First Native Slice

- Do not auto-merge to `dev` or `main`.
- Do not let workers edit `evolve_supervisor/`, gate files, protected files, or cadence policy without human approval.
- Do not replace the existing evolve loop; extend it with durable self-improvement contracts.
- Do not require external Codex/Claude threads for liveness. External agents may execute work, but Thomas owns selection, state, grading, and notification.

## First Implementation Slice

The safest first code slice is a dependency-free state/model layer plus tests:

- Add `thomas/forge/anvil/self_improvement.py` or a small `thomas/forge/anvil/self_improvement/` package with dataclasses for candidates, rubrics, attempts, grade summaries, and notices.
- Add tests with inline fixtures proving JSON round-trip, dedupe fingerprints, protected-path holds, and dashboard-ready summaries.
- Do not touch executor dispatch, UI, protected files, or release metadata until the model contract is stable.

That slice gives future workers a Thomas-owned vocabulary before they start wiring autonomy jobs and dashboard panels.
