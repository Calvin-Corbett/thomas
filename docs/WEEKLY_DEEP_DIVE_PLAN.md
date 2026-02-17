# Weekly Deep Dive Plan (15 Upgrade Tracks)

This is the one-week hardening and capability plan to move Thomas from "good coding bot" to "reliable operator assistant" with stronger continuity, execution momentum, and fewer dumb stall loops.

## Objectives
- Stop context-dropping behavior in ongoing tasks.
- Improve operator-style execution (do first, ask only when blocked).
- Raise conversational quality to closer ChatGPT baseline for non-coding turns.
- Keep token usage intentional (high-context only when needed).
- Add observability so regressions are caught quickly.

## Track 1: Continuation Router (Implemented)
- Problem:
  - Short follow-ups (`ok`, `continue`, `yes`) were interpreted without prior assistant context.
- Implementation:
  - Augment routing input with latest assistant turn for acknowledgement/input follow-ups.
  - Emit `route_input_source` (`prompt_only` vs `history_augmented`) in telemetry.
- Acceptance:
  - Follow-up acknowledgements continue the active flow.
- Validation:
  - Unit tests for history-augmented routing and coding-path continuation.

## Track 2: Requested-Input Continuity Hints (Implemented)
- Problem:
  - User provides token/ID and assistant re-asks or lectures instead of continuing.
- Implementation:
  - Detect likely token/ID replies against prior assistant requests.
  - Inject continuity hints into first iteration prompt context.
- Acceptance:
  - Token/ID replies are consumed as answers and flow continues.
- Validation:
  - Unit tests for token and numeric-ID continuity hints.

## Track 3: Premature Follow-Up Suppression (Implemented)
- Problem:
  - Assistant asks "what next / anything else" before completing active task.
- Implementation:
  - Post-process response text on continuation/action paths to remove generic follow-up prompts unless blocked.
  - Preserve follow-up questions when genuinely blocked on missing input.
- Acceptance:
  - No premature "what next" on active execution flows.
- Validation:
  - Unit tests for suppression and blocked-case exemptions.

## Track 4: Route-Aware Tool Exposure (Implemented)
- Problem:
  - Auto tool selection could hide tools on short continuation turns.
- Implementation:
  - In `auto`, expose tools directly when route path is action-oriented (`coding/debug/planning/research`).
- Acceptance:
  - Short follow-ups can still execute tools without stalling.
- Validation:
  - Unit tests for route-aware tool exposure on short prompts.

## Track 5: Route-Specific History Retention (Implemented)
- Problem:
  - Conversation trimming could drop important recent context in chat/setup flows.
- Implementation:
  - Preserve more recent turns for conversational/meta paths.
  - Keep tighter history for coding/debug for token efficiency.
- Acceptance:
  - Better continuity in setup/admin flows without major token blowup.
- Validation:
  - Unit tests on history policy values in start telemetry.

## Track 6: Startup Guidance Contract + Doctor Visibility (Implemented)
- Problem:
  - "Missing AGENTS" confusion and opaque instruction loading.
- Implementation:
  - Deterministic guidance precedence + fallback behavior.
  - `thomas doctor` prints found/used/missing guidance sources.
- Acceptance:
  - Startup behavior is explainable and deterministic.

## Track 7: Telegram Setup Autopilot (Planned)
- Problem:
  - Setup relies on manual shell copy/paste and user coordination friction.
- Implementation:
  - Add intent-specific setup workflow:
    - detect if token present
    - detect/install telegram extra
    - detect allowlist preference
    - launch polling runner
    - verify bot health via startup checks
  - Track setup state per session.
- Acceptance:
  - "Set up Telegram for me" should drive end-to-end with minimal prompts.
- Test plan:
  - Integration tests with mocked token/runner.

## Track 8: Task State Ledger + API (Planned)
- Problem:
  - No durable per-session "active task / status / blockers" model.
- Implementation:
  - Add task ledger model:
    - `active_goal`
    - `status` (`in_progress|blocked|complete`)
    - `missing_inputs[]`
    - `last_progress`
  - Expose read-only endpoint for UI/inspector.
- Acceptance:
  - Assistant can reference explicit task state instead of pattern guessing.

## Track 9: Workflow Templates (Planned)
- Problem:
  - Recurring flows (deploy, integration, audit, bugfix) are ad hoc.
- Implementation:
  - Add reusable workflow templates with required inputs + checkpoints.
  - Route to templates when intent matches.
- Acceptance:
  - Faster, more consistent execution on known flows.

## Track 10: Response Quality Critic Pass (Planned)
- Problem:
  - Some completions are generic or non-committal.
- Implementation:
  - Lightweight local heuristic critic on final text:
    - detect filler
    - detect unresolved generic question loops
    - detect "non-answer" patterns
  - Retry/rewrite once under strict budget.
- Acceptance:
  - Lower rate of low-value generic responses.

## Track 11: Clarification Budget + Recovery Policy (Planned)
- Problem:
  - Over-questioning in single flow causes frustration.
- Implementation:
  - Cap clarifying questions per active task.
  - If cap hit: make best-effort assumption and proceed.
  - If blocked: ask one precise required input only.
- Acceptance:
  - Fewer redundant questions; clearer blockers.

## Track 12: Memory Pack Compression + Dedupe (Planned)
- Problem:
  - Prompt overhead grows with repetitive memory fragments.
- Implementation:
  - Add dedupe/compaction pass for retrieved memory snippets.
  - Prefer dense summary lines over repeated event text.
- Acceptance:
  - Lower prompt tokens with stable task quality.

## Track 13: Auto-Verification Policy (Planned)
- Problem:
  - Task completion claims can be unverified.
- Implementation:
  - Require verification hooks by task type:
    - coding: tests/lint/syntax
    - integration: startup health check
    - config: read-back validation
- Acceptance:
  - Higher trust in "done" responses.

## Track 14: UI Continuity Panel (Planned)
- Problem:
  - User cannot see why the assistant chose a route or asked for input.
- Implementation:
  - Add panel showing:
    - active task summary
    - route + input source
    - missing inputs
    - blocked reason (if any)
- Acceptance:
  - Easier debugging of weird behavior from UI alone.

## Track 15: Regression + Eval Harness (Planned)
- Problem:
  - Conversational regressions reappear silently.
- Implementation:
  - Add scripted eval suite for:
    - setup flow continuity
    - token/id handoff
    - no premature "what next"
    - short-ack continuation
  - Gate releases on passing score threshold.
- Acceptance:
  - Measurable quality trend across releases.

## Delivery Sequence (Week)
- Day 1-2:
  - Tracks 1-6 stabilization, tests, telemetry checks.
- Day 3:
  - Track 7 (Telegram autopilot) + Track 11 baseline.
- Day 4:
  - Tracks 8-9 (task ledger + templates).
- Day 5:
  - Tracks 10 + 12 (quality critic + memory compaction).
- Day 6:
  - Tracks 13-14 (verification policy + UI continuity panel).
- Day 7:
  - Track 15 (eval harness), regression sweep, release candidate.

## Success Metrics
- Premature follow-up rate (`what next/anything else` before completion): < 2%.
- Setup-flow continuation success (ack/token/id handoff): > 95%.
- Clarification redundancy (same field asked twice): < 1%.
- Toolless stall rate on action routes: < 3%.
- Prompt/completion ratio on casual turns: improved vs current baseline.
