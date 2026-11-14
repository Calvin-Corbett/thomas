# Module: models

| Field            | Value                                                  |
|------------------|--------------------------------------------------------|
| Status           | functional (model discovery, catalog, chat controls)   |
| Last assessed    | 2026-03-18                                             |
| Assessed by      | claude-opus-4-6 (Cowork session)                       |
| Used in prod     | yes — imported by production code                      |
| Has real tests   | not fully assessed                                     |
| Blocking issues  | none identified                                        |

## What This Is

Model utilities — discovery, catalog helpers, chat controls. 2,250 lines
across 8 files, zero placeholders. Handles which AI models Thomas can use,
model selection, and chat control settings.

## Architecture Notes

Connects to preferences (user model selection) and the background preference
model vision (user chooses cloud vs local model for background processing).

## Known Gaps

- No STATUS.md existed before this one (added 2026-03-18)
