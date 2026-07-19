# PROBLEM for UNIFIED-CHAT-CODE-WORK-2026-07-14

## User-visible failure

Thomas has strong but fragmented Chat, Forge, Workforce, Canvas, connector, automation, and skill capabilities. The main experience does not yet present them as the requested three-mode product, and prior work proved ChatGPT parity without proving the full Chat / Code / Work contract.

The screenshot and owner testing exposed concrete failures: a three-deliverable request was combined into a generic Canvas result; Canvas activated too eagerly; the result looked provisional; the conversation falsely reported correction/completion without the original artifacts; and no Chat / Code / Work selectors or mode-filtered histories were present.

## Architectural cause

- Main chat V2, Forge, Workforce, SessionStore, Canvas, task dispatch, and artifact delivery evolved as separate surfaces.
- Generic worker completion and Canvas HTML can be surfaced before product-specific review and durable artifact ranking finish.
- Multi-deliverable classification can confuse numbered content or a combined container with independent deliverables.
- Connection, model, reasoning, autonomy, file, memory, and guardrail settings have several direct/worker/exhaustive paths that can drift.
- Existing related branches contain valuable fixes but also large stale or dirty scopes; blindly merging a worktree would import unrelated metadata and risk branch-policy failure.

## Required correction

Unify the product at the existing main chat surface, keep one canonical V2 execution path, classify/persist mode on the canonical session records, reuse Forge and Workforce live runtimes, and make verified artifacts the completion boundary. Canvas remains a live construction surface; static charts finish as reviewed PDF plus source data, while interactive artifacts may remain HTML.

## Evidence standard

Source wiring and unit tests are necessary but insufficient. The final claim requires real local-browser evidence for all three modes, real tasks/jobs/artifacts, restart persistence, fresh adversarial grading, zero console errors, and a fail-closed line-item rubric.
