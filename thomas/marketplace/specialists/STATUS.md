# Module: specialists

| Field            | Value                                                  |
|------------------|--------------------------------------------------------|
| Status           | functional (specialist sub-agents for orchestrator)    |
| Last assessed    | 2026-03-18                                             |
| Assessed by      | claude-opus-4-6 (Cowork session)                       |
| Used in prod     | yes — imported by production code                      |
| Has real tests   | not fully assessed                                     |
| Blocking issues  | none identified                                        |

## What This Is

Specialist sub-agents that the orchestrator brain dispatches work to.
820 lines across 7 files, zero placeholders. Includes a reasoning
specialist (default/fallback for general conversation, complex reasoning,
multi-step planning).

## Architecture Notes

Works with `thomas/orchestrator/` (brain selects specialists) and
`thomas/chat/` (chat suite v2 delegates to specialists). The robot
characters in the virtual office UI map to specialist bots.

## Known Gaps

- No STATUS.md existed before this one (added 2026-03-18)
