# Module: library

| Field            | Value                                                  |
|------------------|--------------------------------------------------------|
| Status           | functional (research library store and runner)         |
| Last assessed    | 2026-03-18                                             |
| Assessed by      | claude-opus-4-6 (Cowork session)                       |
| Used in prod     | yes — imported by production code                      |
| Has real tests   | not fully assessed                                     |
| Blocking issues  | none identified                                        |

## What This Is

Research library — storage and retrieval for Thomas's research programs.
1,476 lines across 6 files, zero placeholders. Supports Karpathy-style
research programs with checked-in `program.md`, immutable run artifacts,
metric-frontier scoreboards, and accept/reject promotion. Added in 0.14.36.

## What Actually Works

- `store.py` — ResearchLibrary storage and retrieval. Real.
- `research_runner.py` — Research program execution. Real.
- Connected to `thomas research` CLI command.

## Known Gaps

- No STATUS.md existed before this one (added 2026-03-18)
