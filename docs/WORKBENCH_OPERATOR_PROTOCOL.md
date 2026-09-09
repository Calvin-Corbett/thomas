# Workbench Operator Protocol

Last updated: 2026-02-22
Status: active product contract

## Purpose

Define the baseline semantics for Thomas tabs/workbench modules, including user-created tabs:

- Thomas performs the execution work.
- Tabs are control surfaces for intent, orchestration, monitoring, and review.
- Manual in-tab editing is optional and secondary, not the default product meaning.

## Core Contract

For every current or future tab under Thomas workbench surfaces:

1. **AI-first execution**
- A user should be able to express intent and have Thomas execute the task pipeline.
- The tab should expose job dispatch controls, not force users into low-level manual editing as the only path.

2. **Operator visibility**
- Every task/job must expose a clear state (`queued`, `running`, `blocked`, `failed`, `done`).
- Logs/events must be visible in-tab or via a linked timeline panel.

3. **Review and intervention**
- Users can inspect outputs/artifacts and approve/retry/cancel where applicable.
- Tabs should offer safe intervention controls before requiring external app switching.

4. **External tools as engines**
- Existing tools (for example FFmpeg, Blender, Unreal, Kdenlive, Audacity) are integration targets.
- Thomas orchestrates these tools and centralizes status/telemetry.
- Thomas should avoid rebuilding full external editors from scratch unless explicitly scoped.

5. **Future tab baseline**
- New tabs and user-created tabs must inherit this operator-mode baseline by default.
- If a tab intentionally deviates (manual-first), that deviation must be explicitly documented in its plan/spec.

## UX Baseline Language

Workbench tabs should present this stance clearly:

- "Thomas runs the work."
- "This tab is for dispatch, monitoring, and reviewing outputs."

## Implementation Guidance

- Prefer reusable runtime primitives:
  - connector registry
  - job queue/executor
  - event stream
  - artifact store
- Keep tab UIs thin; place heavy execution logic in backend runtimes.
- Preserve fallback behavior when connectors are unavailable.

## Acceptance Checks For New Tabs

Before a new tab is considered complete:

1. Can a non-technical user dispatch work without opening a third-party app first?
2. Are live status and failure reasons visible?
3. Can the user review artifacts in Thomas?
4. Does the tab avoid duplicating a full external professional editor by default?
5. Is the operator-mode statement visible in the tab shell?
