# Module: orchestrator

| Field            | Value                                                  |
|------------------|--------------------------------------------------------|
| Status           | functional (V3 brain with named bot dispatch)          |
| Last assessed    | 2026-03-18                                             |
| Assessed by      | claude-opus-4-6 (Cowork session)                       |
| Used in prod     | yes — imported by production code                      |
| Has real tests   | not fully assessed                                     |
| Blocking issues  | none identified                                        |

## What This Is

The orchestrator brain — decides how Thomas responds. 2,149 lines across
8 files, zero placeholders. V3 architecture: async dispatch with named bot
selection. Thomas replies instantly, bots work in background. Multiple bots
can work in parallel. Casual messages skip routing entirely.

## What Actually Works

- `brain_v3.py` — V3 async dispatch brain. Never blocks. Picks named bots
  from the roster. Parallel task execution. Clean conversation context.
- Named bot selection from the virtual office roster
- Background parallel task dispatch
- Direct-to-Thomas routing for casual messages

## Architecture Notes

This is the "brain" that sits between the chat input and the agent loop.
It decides: is this a casual message (respond directly) or a task (dispatch
to specialist bots)? The specialists module provides the actual bot
implementations.

## Known Gaps

- No STATUS.md existed before this one (added 2026-03-18)
