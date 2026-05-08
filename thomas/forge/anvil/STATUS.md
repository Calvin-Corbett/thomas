# Module: upgrade

| Field            | Value                                                  |
|------------------|--------------------------------------------------------|
| Status           | functional (doppelganger protocol, evolve runtime)     |
| Last assessed    | 2026-03-18                                             |
| Assessed by      | claude-opus-4-6 (Cowork session)                       |
| Used in prod     | yes — imported by production code                      |
| Has real tests   | not fully assessed                                     |
| Blocking issues  | none identified                                        |

## What This Is

Upgrade and self-improvement system. 1,190 lines across 4 files, zero
placeholders. Implements the "Doppelganger Protocol" for safe blue/green
staging and promotion of changes. The `thomas evolve` command (added
0.14.36) syncs blue→green, runs autonomous self-improvement inside the
green mirror, verifies, and gates promotion.

## What Actually Works

- `doppelganger.py` — Blue/green staging protocol. Real.
- `evolve.py` — Autonomous self-improvement runtime. Added 0.14.36. Real.
- Connected to `thomas evolve` CLI and web Evolve mission launch.

## Known Gaps

- No STATUS.md existed before this one (added 2026-03-18)
