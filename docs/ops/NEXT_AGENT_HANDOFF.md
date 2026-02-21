# Next Agent Handoff

Last updated: 2026-02-21T14:10:00-06:00
Latest stability checkpoint commits: `3475aa2`, `36af455`

## Repo Scope

- Active repo root: `F:\DevHub\Thomas`
- Parent `F:\DevHub` is intentionally not an active repo anymore.
- Run Git commands from inside `F:\DevHub\Thomas` only.

## Current Status

- Auto-check framework is present (`scripts/auto_checks.py`) and passes quick mode.
- Timestamped handoff trail exists in `docs/ops/agent_handoff_log.md`.
- iOS in this repo means Companion policy/runtime/API coverage (not native Xcode app output).

## Resume Commands

1. `git rev-parse --show-toplevel`
2. `python scripts/auto_checks.py --quick`
3. `python -m pytest -q tests/test_companion_policy_compliance.py tests/test_server_companion_api.py`
4. `python scripts/append_handoff.py --title "Resume Check" --note "Reviewed current state"`

## Handoff Rule

- Before ending any agent session without final delivery, append a timestamped entry to `docs/ops/agent_handoff_log.md`.
- Preferred command:
  - `python scripts/append_handoff.py --title "Checkpoint" --note "What was done" --note "What is next"`
## Active Folder Coordination

- Before editing, run:
  - `python scripts/active_folders.py check --agent <agent-id> --path <target-folder>`
- Claim folder ownership while working:
  - `python scripts/active_folders.py claim --agent <agent-id> --path <target-folder> --note "<task>"`
- Release after completion:
  - `python scripts/active_folders.py release --agent <agent-id>`
- Full guide: `docs/ops/ACTIVE_FOLDERS_COORDINATION.md`