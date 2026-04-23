# Module: autonomy

| Field            | Value                                                  |
|------------------|--------------------------------------------------------|
| Status           | functional (real job queue, scheduler, approvals)      |
| Last assessed    | 2026-03-18                                             |
| Assessed by      | claude-opus-4-6 (Cowork session)                       |
| Used in prod     | yes — imported by production code                      |
| Has real tests   | not fully assessed                                     |
| Blocking issues  | none identified                                        |

## What This Is

Thomas's autonomous task execution engine. 4,475 lines across 16 files,
zero placeholders. Production-grade job queue, scheduler, approvals, and
audit trail for background work. Uses planner/reviewer/executor agent
pattern with media agent support.

## What Actually Works

- `engine.py` — Main autonomy engine with async job dispatch, planner/reviewer/
  executor agents, media agent error handling. Real production code.
- Agent pattern: PlannerAgent, ReviewerAgent, ExecutorAgent, MediaAgents
- Integrates with `thomas/core/autonomy.py` for autonomy level clamping
- Job queue and scheduling infrastructure
- Approval workflow for autonomous actions
- Audit trail for what the agent did autonomously

## Architecture Notes

This connects to the security vision — autonomous actions should go through
the guardrails engine (when built) to enforce the user's security posture.
Currently uses `thomas/core/autonomy.py` for level clamping but doesn't
gate through the guardrails module (which is placeholder).

## Known Gaps

- No connection to guardrails runtime enforcement (guardrails is placeholder)
- No STATUS.md existed before this one (added 2026-03-18)
