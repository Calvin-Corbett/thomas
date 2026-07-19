# PLAN for THOMAS-CODE-CHAT-FIRST-LIFECYCLE-20260718

- Owner: codex
- Status: in_progress
- Updated At: 2026-07-18T21:56:03+00:00
- Scope: CHANGELOG.md,docs/ops/module_audit_log.json,docs/security/mutating_route_policy_exceptions.json,plans/thomas/WORKBOARD.md,plans/thomas/problems/audit-24h-backstop/PROBLEM.md,plans/thomas/tasks/THOMAS-CODE-CHAT-FIRST-LIFECYCLE-20260718/PLAN.md,pyproject.toml,tests/stress/sweep_deliverable_executability.py,tests/test_agent_loop_token_guard.py,tests/test_chat_delegation_artifact_verification.py,tests/test_chat_delegation_result_summary.py,tests/test_chat_mode_contract.py,tests/test_chat_runtime_policy.py,tests/test_deliverable_ranking.py,tests/test_evolve_agent_routes.py,tests/test_forge_code_settings.py,tests/test_server_access_mode.py,tests/test_server_chat_v2_helpers.py,tests/test_server_preferences_runtime.py,tests/web_node/chat_completion_announcement_retry.mjs,tests/web_node/chat_markdown_renderer.mjs,tests/web_node/unified_code_mode_lifecycle.mjs,tests/web_node/unified_work_support_lifecycle.mjs,thomas/__init__.py,thomas/agent/loop_completion.py,thomas/agent/loop_core.py,thomas/agent/loop_execution.py,thomas/agent/loop_tool_protocol.py,thomas/core/token_economy.py,thomas/forge/anvil/dispatch_agent_loop.py,thomas/forge/anvil/forge_code_runner.py,thomas/preferences/_db.py,thomas/preferences/_prefs.py,thomas/server/app_keys.py,thomas/server/app_lifecycle.py,thomas/server/app_middleware_handlers.py,thomas/server/app_middleware_security.py,thomas/server/chat_delegation_artifact_verification.py,thomas/server/chat_delegation_deliverable.py,thomas/server/chat_delegation_deliverable_postprocess.py,thomas/server/chat_delegation_result_policy.py,thomas/server/chat_delegation_runner.py,thomas/server/routes/chat_v2_announcements.py,thomas/server/routes/deliverable_aiohttp.py,thomas/server/routes/evolve_agent_http_support.py,thomas/server/routes/evolve_agent_routes.py,thomas/server/web/chat.html,thomas/server/web/js/unified_code_mode.js,thomas/server/web/js/unified_work_mode.js

## Summary

THOMAS-CODE-CHAT-FIRST-LIFECYCLE-20260718

## Approach

- Checkpoint the already-tested Code intent separation and presentation-only mode switching so the next slice starts from a clean tree.
- Add deferred lifecycle coverage for first-turn Work onboarding, real Chat/Code/Work hidden completion, and dispatcher-entrypoint intent forwarding.
- Remove the remaining `adapterActive` bootstrap exits that abandon first-turn Work onboarding after a presentation-only switch.
- Make Chat refresh mode chrome whenever its busy state changes, including hidden completion.
- Replay each mode organically in one browser session and switch between modes while work is still running.

## Fresh review findings carried into the follow-up

- Work first-turn onboarding bootstrap can exit after creating partial state when Work is hidden.
- Current shell tests prove fake-adapter switching but do not yet prove all three real adapters complete while hidden.
- Raw-intent coverage needs a dispatcher-entrypoint assertion, not only helper-level forwarding.
- Chat's running-tab marker can remain stale after a hidden response completes.
- Suspicious-prompt screening must inspect all untrusted model-visible history, not only the routing intent.
- Work reconciliation polling must resume when an active job is revisited.
- The Code activity drawer resize affordance needs keyboard support.
- The project-folder picker must preserve plain-text backend errors instead of surfacing JSON parser noise.
- Drawer preference storage failures need quiet diagnostic evidence instead of empty catches.

These findings are intentionally recorded in this local WIP checkpoint because the startup router requires a clean checkpoint before any more product edits. They are not release-complete claims.

## Completion-safe budget separation rubric

| Line item | User-visible outcome | Organic scenario | Hostile/long scenario | Required receipt | Exact pass condition |
| --- | --- | --- | --- | --- | --- |
| Default cumulative spend | Thomas reports token use without terminating normal work | A fresh Chat/Code/Work profile completes a multi-turn task with no budget preference saved | Simulated session usage reaches the displayed session threshold | Saved-preference readback plus provider-call events | `throttle_on_budget` is false by default and no cumulative-token exception is raised |
| Explicit hard spending cap | A user who deliberately enables a hard cap still gets deterministic enforcement | Enable the cap, spend to the configured limit, then start another call | Concurrent reservations compete for the final allowance | Budget-ledger reservation and rejection rows | The explicitly enabled cap blocks atomically without overspend or silent fallback |
| Agent pass limits | Effort controls bounded attempts, not arbitrary cumulative tokens | A tool task uses its configured passes and returns a final handoff | A model keeps requesting tools until the pass cap | Agent event count and terminal event | The loop stops at the pass cap and truthfully reports incomplete work when completion evidence is absent |
| Model context safety | Context-window limits are handled by trimming/compaction rather than a task-wide token stop | A long thread crosses the compaction threshold and continues | Large tool history plus long user context remains within the provider window | Compaction/trim telemetry and final provider receipt | Every provider request fits the model context window; no cumulative raw-token guard ends the task |
| High per-pass usage | Expensive individual passes produce warnings, not false task failure | A valid large-context pass continues to its next planned pass | Simulated prompt usage exceeds the old 24k threshold while still fitting the model window | Token report warning plus terminal event | Warning is recorded, no `AGENT_ERROR` is emitted solely for raw prompt-token spend |
| Mode survival | Chat, Code, and Work continue while the user changes product tabs | Start a long task, switch modes twice, then return | Switch during initial Work bootstrap and while Code tools are active | Browser DOM state, persisted conversation, execution ID | One execution continues, one final result persists, and no mode switch aborts or duplicates it |

Critical failures are not averaged away: a raw cumulative-token stop, an untruthful completion, a duplicated execution, or a lost hidden-mode result fails the checkpoint.

## Live evidence

- Preferences API on the exact 0.19.0 server reports `throttle_on_budget=false`, while the explicit opt-in hard-cap tests still reject atomically.
- Code run `run-_HcSDNcvLtWYGH3r` survived presentation-only mode switches, completed with return code 0, and wrote the independently verified five-item proof file with SHA-256 `DF977F71740A25C365FD1989DBB47396900536BBA4D6317CA037E27C5580F9E8`.
- Work onboarding survived Chat/Code switches, mapped five distinct daily workflows, accepted one selected flow, and asked the qualifying queue-condition question before configuring automation.
- Chat execution `exec-10574c92fd5b` survived Chat → Code → Work → Chat, persisted all eight requested steps and `CHAT_SWITCH_SURVIVED_0718_FINAL`, and ended `state=completed`, `proof_status=verified`.
- The same saved Chat answer was reloaded after the UI change; the accessibility tree contained semantic headings/lists and no raw `###` heading, while raw user HTML remained escaped.
- Long context-pressure proof completed six tool/model passes with 120,000+ reported provider tokens, auto-compacted the stored conversation, trimmed the next request to fit, and reached `CONTEXT_PRESSURE_RUN_DONE` without a raw-token `AGENT_ERROR`.
- Chat verification regressions cover prefixed action claims, procedural examples, explicit artifact requests, Markdown-in-chat, exact multiline answer preservation, and verified-file/unverified-side-effect separation.
- Executable Code and Work harnesses now exercise folder-picker success/cancel/error/malformed-200 behavior, pointer-cancel cleanup, hidden-mode completion, live reconciliation, and active-draft requeue.
- A real Code continuation stayed active through Code to Work to Chat to Code, emitted four readable milestones over 18 checks, changed two files, and rendered the Trey game with its `MODE SWITCH SURVIVED` status inside the isolated preview.
- A real Chat artifact turn exposed a false terminal failure after an optional skill-enrichment error; after the verifier fix, exact rerun `exec-fb2cf834e843` survived Chat to Work to Code to Chat, completed as Done, and opened a Canvas result containing exactly `CHAT SURVIVED`.
- A real Work deployment stayed active through Work to Chat to Code to Work and mission `523e255afa50484abff196aa91534c40` succeeded on its first attempt with final output `LOCAL_WORK_PROOF_OK` and no fallback.
- The isolated preview sweep passed 11/11 checks for capability entry, cookie gating, traversal containment, root-relative CSS/modules/data/workers, API-route absence, verifier outcomes, and strict parent/preview response policy; the focused preview and route suites passed 52 tests plus three subtests.
- Fresh adversarial security review found no P0 issue but exposed four completion/security gaps: guessed provider TPM termination, basename-only artifact verification, same-tool failure erasure, and reusable/unbounded preview origins. The slice now uses explicit-only local TPM policy plus resumable real 429 handling, verifies recorded relative paths, preserves every failed action, clears prior origin storage, denies service workers, expires sockets automatically, and caps active previews.
- Security review: 23 webhook/CSRF/policy tests passed with one documented pre-existing Stripe local-mode xfail; strict mutating-route policy is 232/232 covered, release hygiene passes, and the strict aggregate security audit has zero errors.
- Pre-final consolidated suite: 285 passed, 59 subtests passed, with one known environment-dependent optional-tool policy inventory test deselected (`424` dynamically registered optional tools); the post-review adversarial subset adds 61 passing tests.
- `git diff --check` and Ruff pass. The module-audit gate passes with fresh signed entries. The repository-wide plan-structure gate remains red on a large pre-existing backlog of historical plan/index references unrelated to this scope; the docs runner recorded the exact baseline in `audit-24h-backstop`.
