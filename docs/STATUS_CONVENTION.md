# STATUS Convention

STATUS.md files are the human-readable truth source for module maturity.

## Purpose

- Tell a future agent or human whether a module is real, scaffold, mixed, or placeholder-heavy.
- Record whether the module is production-used, tested, blocked, or intentionally staged.
- Make placeholder state explicit so committing a scaffold is not mistaken for a finished implementation.

## Required Fields

Every module-level STATUS.md should include at minimum:

- Status
- Last assessed
- Assessed by
- Used in prod
- Has real tests
- Blocking issues

## Status Vocabulary

- unctional: production-used or otherwise real and operational.
- wip: partially real, partially incomplete, but active work exists.
- scaffold: intentional structure exists, but key implementation is absent.
- placeholder: only source placeholders exist; runtime must fail fast or stay disconnected.
- rchived: intentionally retained for history, not active development.

## Placeholder Rules

If a Python source file is a source placeholder, it must include:

- placeholder-why
- placeholder-scope_to_finish
- placeholder-owner
- placeholder-exit_rule
- placeholder-acceptance

The owning module STATUS.md must also mention that placeholder state plainly.
Subdirectory placeholders can roll up into the nearest meaningful module STATUS.md
when a per-subdirectory STATUS.md would add noise.

Examples:

- 	homas/agent/hooks_registry.py rolls up into 	homas/agent/STATUS.md
- 	homas/server/routes/chat_agent_mode.py rolls up into 	homas/server/STATUS.md
- 	homas/orchestration/*.py rolls up into 	homas/orchestration/STATUS.md

## Commit Policy

Placeholder files are allowed to be committed when all of the following are true:

- the file is explicitly annotated as a placeholder,
- the parent module STATUS.md names the gap,
- the runtime either fails fast or remains intentionally disconnected,
- tests do not falsely claim the placeholder is a working implementation.

## Non-Committable Local Noise

These should normally be ignored or deleted instead of committed:

- root .tmp_* scratch files
- startup logs like server_startup_log.txt
- local active-index markers such as indices/ACTIVE.json and indices/ACTIVE.lock
- other machine-local runtime artifacts under ignored runtime paths

## Assessment Rule

When a module changes materially, update its STATUS.md in the same changeset if the
truth about that module changed.