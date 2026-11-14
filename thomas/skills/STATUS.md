# Module: skills

| Field            | Value                                                  |
|------------------|--------------------------------------------------------|
| Status           | functional (wired into the agent skills runtime) |
| Last assessed    | 2026-06-05                                                  |
| Assessed by      | claude-opus-4-8 (wiring truth-up)      |
| Used in prod     | yes — imported by agent/skills_runtime, agent/skills_policy, cli/compat_skills, cli/parity_support, cli/repl_skills |
| Has real tests   | not assessed       |
| Blocking issues  | none                                  |

## What This Is

The native skill subsystem: discovers skill bundles on disk, parses their
manifests/frontmatter, sandboxes draft creation/promotion, and runs no-copy
security checks before a skill is promoted.

**Stats:** 5 Python files, 770 lines total (`__init__.py` 42, `_manifest.py`
147, `_runtime.py` 144, `_sandbox.py` 293, `_security.py` 144).

## Honest Assessment

Real, functional code — not a placeholder. `__init__.py` re-exports the public
API consumed by the agent. `_manifest.py` parses skill frontmatter/bundles
(`SkillBundle`, `read_skill_bundle`, `validate_skill_bundle`). `_runtime.py`
discovers native + external skill roots (`discover_native_skills`,
`discover_native_skill_roots`, `builtin_skill_roots`). `_sandbox.py` manages
draft creation, review, and promotion (`create_skill_draft`,
`promote_skill_draft`, `review_skill_draft`). `_security.py` builds no-copy
reports and validates recreated bundles. It is imported by the agent runtime
(`thomas/agent/skills_runtime.py:19`, `thomas/agent/skills_policy.py:13`) and
by the CLI (`cli/compat_skills.py`, `cli/parity_support.py`,
`cli/repl_skills.py`).

## Known Gaps

- Test coverage not assessed
