# Unified Thomas Chat / Code / Work Fail-Closed Rubric

- Schema: `thomas-unified-chat-code-work-v1`
- Frozen before product implementation: 2026-07-14
- Completion rule: every `P0` row must be `PASS`; no average or bonus can waive a failed, blocked, or unverified critical row.
- Baseline rule: all rows start `UNVERIFIED`, even when source code exists. `PASS` requires the named automated, browser, adversarial, and proof evidence.
- Proof root: `artifacts/unified_chat_code_work/`

## Evidence abbreviations

- Browser suites: `B-MODES`, `B-CHAT`, `B-CODE`, `B-WORK`, `B-CANVAS`, `B-SETTINGS`, `B-PERSIST`, `B-RESPONSIVE`, `B-A11Y`.
- Adversaries: `A-INTENT`, `A-COMPLETION`, `A-CODE`, `A-WORK`, `A-CONNECTORS`, `A-CANVAS`, `A-SETTINGS`, `A-VISUAL`.
- Provisional implementation paths are refined by the read-only audit before the corresponding row is implemented.

| ID | Pri | Requirement | Implementation mapping | Automated test mapping | Browser | Adversarial | Required proof | Status |
|---|---|---|---|---|---|---|---|---|
| M01 | P0 | Chat / Code / Work selector directly above Search Chats; Chat default | `thomas/server/web/chat.html`; main chat state contract in `thomas/server/routes/chat_v2.py` | `tests/test_web_chat_surface_contract.py`; new `tests/test_chat_mode_contract.py` | B-MODES | A-VISUAL | `modes/default-chat.png`, DOM assertion | UNVERIFIED |
| M02 | P0 | Mode switch changes history, composer, controls, and surrounding UI | `chat.html`; `thomas/chat/session_store.py`; chat V2 session payload | `test_chat_mode_contract.py`; `tests/test_session_store.py` | B-MODES | A-INTENT | `modes/switch-matrix.json` | UNVERIFIED |
| M03 | P0 | Chat, Code, and Work histories stay isolated and durably filtered | `session_store.py`; `chat_v2.py`; Workforce/Forge session adapters | `test_chat_mode_contract.py`; restart API test | B-PERSIST | A-WORK | `history/isolation-restart.json` | UNVERIFIED |
| C01 | P0 | Ordinary questions do not unnecessarily launch workers | `thomas/agent/dispatch.py`; `chat_v2.py` | `tests/test_server_chat_v2_max_mode.py`; intent matrix | B-CHAT | A-INTENT | `chat/direct-answer.json` | UNVERIFIED |
| C02 | P0 | Appropriate task requests execute directly/hybrid with honest progress | `chat_v2.py`; `thomas/server/chat_delegation*.py`; `worker_runtime.py` | delegation/worker/progress tests | B-CHAT | A-COMPLETION | `chat/task-progress.jsonl` | UNVERIFIED |
| C03 | P0 | Genuine N-deliverable request fans out exactly N one-to-one | dispatch/delegation/session/workspace runtime | multi-deliverable intent + isolation tests | B-CHAT | A-INTENT | `chat/three-deliverables.json` | UNVERIFIED |
| C04 | P0 | Procedures, lists, combined containers, approvals, and discussion are not false fan-out | intent classifier in chat V2/delegation | adversarial classification parameter matrix | B-CHAT | A-INTENT | `chat/non-fanout-cases.json` | UNVERIFIED |
| C05 | P0 | Each deliverable has isolated workspace, status, review, and artifacts | delegation session/worker config/artifact verification | workspace/artifact isolation tests | B-CHAT | A-COMPLETION | `chat/deliverable-workspaces.json` | UNVERIFIED |
| C06 | P0 | Acknowledgement, promise, placeholder, or status text cannot complete work | `chat_delegation_artifact_verification.py`; completion evidence | completion-negative tests | B-CHAT | A-COMPLETION | `chat/completion-rejections.json` | UNVERIFIED |
| C07 | P0 | Hidden result review occurs before presentation | delegation verifier; Canvas review; deliverable ranking | review-order and failure tests | B-CHAT | A-COMPLETION | `chat/review-events.jsonl` | UNVERIFIED |
| C08 | P0 | Chat supports files, tools, memory, and file-access controls | chat attachments; worker config; tool registry; memory context | attachment/tool/memory/file-policy tests | B-CHAT | A-SETTINGS | `chat/files-tools-memory.json` | UNVERIFIED |
| C09 | P0 | Chat history, artifacts, settings, and Canvas survive restart | SessionStore; artifact/task stores; Canvas session persistence | restart lifecycle tests | B-PERSIST | A-COMPLETION | `persistence/chat-restart.json` | UNVERIFIED |
| D01 | P0 | Verified completion only; failures/blockers are explicit and honest | action receipt, artifact verifier, worker finalization | negative completion/receipt tests | B-CHAT | A-COMPLETION | `completion/fail-closed.json` | UNVERIFIED |
| K01 | P0 | Code mode reuses the strongest live Forge runtime, not a mock or old page | live Forge UI/API paths from audit; main `chat.html` adapter | Forge adapter contract tests | B-CODE | A-CODE | `code/runtime-provenance.json` | UNVERIFIED |
| K02 | P0 | Code task history is separate, durable, and project-scoped | Forge store + canonical session mode metadata | Forge store/session restart tests | B-CODE | A-CODE | `code/history-restart.json` | UNVERIFIED |
| K03 | P0 | Project/repository selector and file tree/file access work | Forge project/store/file-access runtime | Forge project/file access tests | B-CODE | A-CODE | `code/project-file-tree.png` | UNVERIFIED |
| K04 | P0 | Planning, progress, reasoning, tools, terminal, diffs, tests, verification are visible | Forge event stream/deliverables/git/build verify | Forge event contract tests | B-CODE | A-CODE | `code/activity-timeline.jsonl` | UNVERIFIED |
| K05 | P0 | Useful next-action suggestions and risky-operation approvals work | Forge UI/event/approval broker | suggestions + approval tests | B-CODE | A-CODE | `code/suggestion-approval.json` | UNVERIFIED |
| K06 | P0 | Honest failures/blockers and cancellation/steering | Forge dispatcher/event stream | fail/cancel/steer tests | B-CODE | A-CODE | `code/failure-steer.json` | UNVERIFIED |
| K07 | P0 | Real code task edits, tests, runs, and yields a verified result | Forge dispatch/build verify/deliverables | real sandbox fixture integration | B-CODE | A-CODE | `code/real-task/` | UNVERIFIED |
| K08 | P0 | Code mode creates games/sites/visualizations/graphs/docs and runs them | Forge code deliverables + artifact pipeline | artifact-matrix integration | B-CODE | A-CODE | `code/artifact-matrix.json` | UNVERIFIED |
| W01 | P0 | Work view keeps chat and adds premium job/app tiles | `chat.html`; live Workforce UI adapter | Work surface DOM contract | B-WORK | A-VISUAL | `work/job-tiles.png` | UNVERIFIED |
| W02 | P0 | Create/select/pause/resume/edit/archive/inspect jobs | `thomas/workforce/*`; `thomas/server/routes/workforce.py`; UI adapter | Workforce lifecycle tests | B-WORK | A-WORK | `work/job-lifecycle.json` | UNVERIFIED |
| W03 | P0 | Selecting a job filters history to only that job | Workforce job ID + SessionStore mode context | job history isolation tests | B-WORK | A-WORK | `work/job-history-isolation.json` | UNVERIFIED |
| W04 | P0 | Customizable dashboard sits alongside job chat | Workforce app/dashboard runtime + main UI adapter | dashboard state tests | B-WORK | A-VISUAL | `work/job-dashboard.png` | UNVERIFIED |
| W05 | P0 | Job runs, schedules, failures, outputs, approvals, activity are visible | Workforce service; task/scheduler/approval stores | job observability tests | B-WORK | A-WORK | `work/job-activity.json` | UNVERIFIED |
| W06 | P0 | Job onboarding is organic, begins with job purpose, then asks relevant follow-ups | Workforce onboarding conversation policy in V2 | varied-job conversation tests | B-WORK | A-WORK | `work/onboarding-transcripts.jsonl` | UNVERIFIED |
| W07 | P0 | No rigid generic questionnaire is presented | onboarding policy/UI | negative scripted-questionnaire test | B-WORK | A-WORK | `work/onboarding-variation.json` | UNVERIFIED |
| W08 | P0 | Each job owns history, memory/workflow knowledge, dashboard, and artifacts | Workforce job state; SessionStore; memory/skill scopes | cross-job isolation/restart tests | B-PERSIST | A-WORK | `work/job-isolation.json` | UNVERIFIED |
| W09 | P0 | Scheduled and event-driven automations can be managed and run | scheduler/workflow/Workforce integration | automation lifecycle/recovery tests | B-WORK | A-WORK | `work/automation-run.json` | UNVERIFIED |
| W10 | P0 | Actual supported connectors are selectable with clear identities | integrations/connector registry + Workforce bindings | connector catalog/binding tests | B-WORK | A-CONNECTORS | `work/connector-catalog.json` | UNVERIFIED |
| W11 | P0 | Multiple accounts per connector and reuse/job-specific assignment work | connector account store + job binding model | two-account isolation tests | B-WORK | A-CONNECTORS | `work/multi-account.json` | UNVERIFIED |
| W12 | P0 | Job-private skills are learned and inactive elsewhere by default | skill runtime + job skill pool | job/global skill scope tests | B-WORK | A-WORK | `work/private-skill-isolation.json` | UNVERIFIED |
| W13 | P0 | Explicit promotion moves a job skill to global library | skill promotion control/API | promotion approval/lifecycle tests | B-WORK | A-WORK | `work/skill-promotion.json` | UNVERIFIED |
| S01 | P0 | Model selector exposes GPT-5.6 Sol, Terra, Luna | `thomas/models/catalog_rules.py`; `chat.html`; settings surfaces | model catalog/UI contract tests | B-SETTINGS | A-SETTINGS | `settings/gpt56-options.png` | UNVERIFIED |
| S02 | P0 | Reasoning exposes None/Low/Medium/High/xHigh/Max | model capabilities; chat/settings UI; request schema | reasoning option/normalization tests | B-SETTINGS | A-SETTINGS | `settings/reasoning-options.png` | UNVERIFIED |
| S03 | P0 | Model/reasoning propagate through direct chat and normal workers | chat V2 + worker config/runtime | request-to-worker trace tests | B-SETTINGS | A-SETTINGS | `settings/direct-normal-trace.json` | UNVERIFIED |
| S04 | P0 | Settings propagate through exhaustive workers and fan-out | exhaustive runtime + delegation worker config | exhaustive/fanout trace tests | B-SETTINGS | A-SETTINGS | `settings/exhaustive-fanout-trace.json` | UNVERIFIED |
| S05 | P0 | Settings propagate through Code mode and Work jobs/automations | Forge/Workforce dispatch config | Code/Work propagation tests | B-SETTINGS | A-SETTINGS | `settings/code-work-trace.json` | UNVERIFIED |
| S06 | P0 | Autonomy, file access, guardrails, memory, token settings propagate everywhere | request/settings schema; all dispatch adapters | full cross-mode setting matrix | B-SETTINGS | A-SETTINGS | `settings/full-matrix.json` | UNVERIFIED |
| S07 | P0 | Valid signed-in ChatGPT connection remains accurate/persistent without reconnect prompt | OAuth secret root/profile; server app; setup/settings | OAuth root/profile/restart tests | B-PERSIST | A-SETTINGS | `settings/oauth-restart.json` | UNVERIFIED |
| V01 | P0 | Canvas activates only for genuine visual/interactive requests | Canvas intent contract in chat delegation/V2 | positive/negative Canvas intent matrix | B-CANVAS | A-CANVAS | `canvas/activation-matrix.json` | UNVERIFIED |
| V02 | P0 | Visual construction streams live into Canvas | Canvas stream emitter/session/iframe UI | event-order/partial-render tests | B-CANVAS | A-CANVAS | `canvas/live-build.webm`, events | UNVERIFIED |
| V03 | P0 | Hidden review checks accuracy, labels, values, clipping, layout, visibility, polish | Canvas review module + artifact verifier | rejection/fix/review tests | B-CANVAS | A-CANVAS | `canvas/review-report.json` | UNVERIFIED |
| V04 | P0 | Static chart primary artifact is polished PDF, with CSV/XLSX source data | Canvas renderer + deliverable ranking/export | chart PDF/data integration test | B-CANVAS | A-CANVAS | `canvas/chart.pdf`, `.csv`/`.xlsx` | UNVERIFIED |
| V05 | P0 | Static chart does not expose `index.html` as primary result | deliverable ranking/UI | ranking negative test | B-CANVAS | A-CANVAS | `canvas/static-artifact-ranking.json` | UNVERIFIED |
| V06 | P0 | HTML remains valid primary deliverable for games/apps/sites/interactive dashboards | intent/artifact classification | interactive artifact tests | B-CANVAS | A-CANVAS | `canvas/interactive-ranking.json` | UNVERIFIED |
| V07 | P0 | Canvas rejects generic/hidden/offscreen/disappearing/misleading evidence | Canvas review/security validation | adversarial HTML fixture matrix | B-CANVAS | A-CANVAS | `canvas/rejected-fixtures.json` | UNVERIFIED |
| V08 | P0 | Legitimate interactions, loading, tooltips, decoration remain allowed | Canvas validator exceptions | legitimate fixture matrix | B-CANVAS | A-CANVAS | `canvas/allowed-fixtures.json` | UNVERIFIED |
| Q01 | P0 | Deliberate spacing, hierarchy, alignment, no excess blank Canvas | `chat.html` styles/layout and Canvas sizing | DOM/layout assertions | B-RESPONSIVE | A-VISUAL | desktop/tablet/mobile screenshots | UNVERIFIED |
| Q02 | P0 | Responsive, accessible, keyboard-operable mode and job controls | semantic markup/focus management | accessibility/static checks | B-A11Y | A-VISUAL | axe/keyboard report | UNVERIFIED |
| Q03 | P0 | Useful empty/loading/error/disconnected states; no internal warnings | main UI state renderers | state renderer tests | B-MODES | A-VISUAL | `quality/state-matrix.png` | UNVERIFIED |
| Q04 | P0 | Zero browser console errors across all required flows | all affected UI/runtime files | browser console gate | all browser suites | A-VISUAL | `quality/console.json` | UNVERIFIED |
| E01 | P0 | Real Work job is created and run successfully | integrated Work runtime | job integration fixture | B-WORK | fresh grader | `end_to_end/work-job/` | UNVERIFIED |
| E02 | P0 | True three-deliverable request returns three separate verified artifacts | integrated Chat runtime | fan-out integration fixture | B-CHAT | fresh grader | `end_to_end/three-deliverables/` | UNVERIFIED |
| E03 | P0 | Chart visibly builds then delivers reviewed PDF/data | integrated Canvas/artifact runtime | chart integration fixture | B-CANVAS | fresh grader | `end_to_end/chart/` | UNVERIFIED |
| E04 | P0 | Playable game is created and tested | Code/Canvas runtime | game fixture + interaction test | B-CODE | fresh grader | `end_to_end/game/` | UNVERIFIED |
| E05 | P0 | Sol/Terra/Luna each run with verified settings propagation | integrated provider runtime | provider trace integration | B-SETTINGS | fresh grader | `end_to_end/gpt56/` | UNVERIFIED |
| E06 | P0 | Restart preserves all three modes, histories, jobs, artifacts, settings | all canonical persistence stores | restart matrix | B-PERSIST | fresh grader | `end_to_end/restart/` | UNVERIFIED |
| E07 | P0 | Static/lint/compile/architecture/boot/repository policy gates pass | affected repo | gate commands | n/a | fresh gate auditor | `gates/final.json` | UNVERIFIED |
| E08 | P0 | Exact completed worktree server is restarted and left running locally | run/serve path from this branch | health/API smoke | all browser suites | fresh release grader | `handoff/server.json` | UNVERIFIED |

## Final grader rule

Each final adversarial family is assigned to a newly created agent with no inherited grader conclusion. A grader receives the frozen rubric, product URL, and proof locations, then independently returns row-level pass/fail evidence. Any critical disagreement is resolved by rerunning the behavior, not by averaging opinions.
