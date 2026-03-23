# Module: learning

| Field            | Value                                                  |
|------------------|--------------------------------------------------------|
| Status           | scaffold (SKELETON — all files are import-safe stubs)  |
| Last assessed    | 2026-03-18                                             |
| Assessed by      | claude-opus-4-6 (Cowork session)                       |
| Used in prod     | imported but skeleton only — does nothing at runtime   |
| Has real tests   | no                                                     |
| Blocking issues  | 100% skeleton, 49 total lines across 7 files           |

## What This Is

Planned learning/adaptation surface. Currently a domain skeleton with
import-safe placeholder stubs. All 7 files are 7 lines each — just the
skeleton `__getattr__` hook that makes imports not crash.

Files: `__init__.py`, `analyzer.py`, `feedback.py`, `injector.py`,
`store.py`, `teacher.py`, `types.py`

**None of these do anything.** They exist so that imports don't fail.

## What This Should Become

A system where Thomas learns from interactions — feedback loops, teaching
from the user, storing learned patterns, analyzing what works. Connects to
the memory and preferences vision (background model that learns about you).

## Known Gaps

- 100% skeleton, zero functional code
- No STATUS.md existed before this one (added 2026-03-18)
