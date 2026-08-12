# PLAN for UNIFIED-CHAT-CODE-WORK-2026-07-14

- Owner: codex-unified-chat-code-work
- Status: in progress
- Updated At: 2026-07-14T21:45:00-05:00
- Branch: `codex/unified-chat-code-work-20260714`
- Clean base: `dbfefc220660478d1f1d26c6579ba75d3a45b00c` (Thomas 0.18.0 parity proof, direct descendant of `dev` at `89d708d4`)
- Local only: no push or PR without explicit user authorization

## Objective

Deliver and prove the complete unified Thomas Chat / Code / Work experience in the main Thomas UI. The selector is only the entry point: all three modes, their mode-specific histories and controls, Forge and Workforce reuse, settings propagation, Canvas review and artifact delivery, persistence, and real browser behavior must converge together.

## Inputs to preserve

- The committed Thomas 0.18.0 ChatGPT-parity work through `dbfefc22`.
- The staged signed-in ChatGPT recovery fixes in `codex/gpt56-live-fix-20260714`.
- The uncommitted reliability and Canvas review work in `codex/unified-chat-fix-20260714`, ported selectively after diff review.
- Live Forge, Workforce, SessionStore, chat V2, Canvas, task, connector, automation, and skill primitives already present in the repo.

## Delivery sequence

1. Freeze this fail-closed rubric before product code changes.
2. Complete read-only live-path and related-branch audits; replace every provisional file mapping with the canonical path.
3. Port the already-tested ChatGPT connection, GPT-5.6, dispatch, completion-evidence, multi-deliverable, and Canvas-review fixes without copying Workboard metadata.
4. Add one canonical mode contract to main chat and SessionStore; do not add a new chat pipeline or a third history store.
5. Move the strongest live Forge experience into Code mode and prove a real repository task.
6. Evolve live Workforce into Work mode with job onboarding, tiles/dashboard, job histories, runs, automations, connectors, multiple identities, and job-private skills/memory.
7. Enforce visual-intent Canvas activation, hidden review, static-chart PDF/data delivery, and interactive HTML exceptions.
8. Add deterministic tests, then run fresh adversarial agents and a real local browser matrix. Iterate until every critical row in `RUBRIC.md` passes.
9. Run repository gates, restart the server from this exact worktree, and leave it running for owner testing.

## Non-negotiable stop rules

- Any critical rubric row marked `FAIL`, `BLOCKED`, or `UNVERIFIED` means the goal is not done.
- No acknowledgement, promise, placeholder, progress text, or unverified path may be treated as completion.
- No old/dead UI path, parallel V3 chat path, shallow Forge mock, or separate Workforce clone may be introduced.
- No Workboard metadata, claim, or unrelated branch dirt may be copied into product commits.
- No push, PR, protected-file change, or guard weakening without explicit owner approval.

## Verification families

- Focused unit/API/contract tests for every affected runtime.
- Architecture, compile/static, lint, boot, claim, scope, and commit dry-run gates.
- Headed browser tests for Chat, Code, Work, responsive layouts, keyboard/accessibility, persistence, and console/network errors.
- Fresh adversarial reviewers for intent classification, verified completion, Canvas, settings propagation, connectors, persistence, and visual quality.
- Durable proof under `artifacts/unified_chat_code_work/` plus a machine-readable final rubric status.
