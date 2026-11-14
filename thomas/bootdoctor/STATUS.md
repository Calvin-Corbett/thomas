# Module: bootdoctor

| Field            | Value                                                  |
|------------------|--------------------------------------------------------|
| Status           | functional (subprocess-spawned + console-script) |
| Last assessed    | 2026-06-05                                                  |
| Assessed by      | claude-opus-4-8 (wiring truth-up)      |
| Used in prod     | yes — spawned by `thomas/server/app_core.py` and exposed as the `bootdoctor` console-script (pyproject.toml:80) |
| Has real tests   | not assessed       |
| Blocking issues  | none                                  |

## What This Is

BootDoctor standalone CLI package.

**Stats:** 2 Python files, 828 lines total.

## Honest Assessment

**Contains real algorithms and logic** with actual implementations. It IS
wired into production: the server spawns a boot-doctor report as a subprocess
(`thomas/server/app_core.py`, `_bootdoctor_spawn_report` around line 451), and
it is exposed as the `bootdoctor` console-script entry point
(`pyproject.toml:80` → `thomas.bootdoctor.__main__:main`).

## Known Gaps

- Test coverage not assessed
