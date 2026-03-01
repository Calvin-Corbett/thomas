# Next Agent Handoff

Last updated: 2026-02-27T00:00:00-06:00
Latest stability checkpoint commits: `3475aa2`, `36af455`, `7fb8de5`, `d865441`, `8409a3b`

## Repo Scope

- Active repo root: `F:\DevHub\Thomas`
- Parent `F:\DevHub` is intentionally not an active repo anymore.
- Run Git commands from inside `F:\DevHub\Thomas` only.

## Current Status

- Auto-check framework is present (`scripts/auto_checks.py`) and passes quick mode.
- Timestamped handoff trail exists in `docs/ops/agent_handoff_log.md`.
- Active-folder coordination has strict overlap blocking + pre-commit staged guard.
- Pre-commit guard now requires explicit agent identity by default.
- iOS in this repo means Companion policy/runtime/API coverage (not native Xcode app output).
- All non-task-manager implementation agents are required to bootstrap with `agent_bootstrap_claim.py` for first claim in a terminal/session so parent role and dispatch are standardized.

## Resume Commands

1. `git rev-parse --show-toplevel`
2. `python scripts/auto_checks.py --quick`
3. `python scripts/active_folders.py whoami`
4. `python -m pytest -q tests/test_companion_policy_compliance.py tests/test_server_companion_api.py`
5. `python scripts/append_handoff.py --title "Resume Check" --note "Reviewed current state"`

## Task Board Standard

- Non-task-manager implementation agents must use bootstrap claim + implicit orchestration:
  - `python scripts/agent_bootstrap_claim.py --agent "<agent>" --scope "<scope>" --task "<summary>" --name "<name>"`
- Bootstrap defaults are parent + auto-dispatch; leave dispatch on unless this is an explicit one-shot (`--no-auto-dispatch`).
- Bootstrap dispatch is clamped to at least two workers by default and should keep moving when READY lanes exist.
- Workers should release or mark `READY` on completion so the next assignment starts automatically, unless user explicitly asks to stay on a lane.
- Use workboard messaging (or equivalent) for blockers and scope-change requests.

## Handoff Rule

- Before ending any agent session without final delivery, append a timestamped entry to `docs/ops/agent_handoff_log.md`.
- Preferred command:
  - `python scripts/append_handoff.py --title "Checkpoint" --note "What was done" --note "What is next"`

Standard completion cadence:

- Task-manager tasks can remain at their current lane if instructed.
- Non-task-manager agents should default to `complete -> release/READY -> next assignment` behavior without waiting for explicit prompts.

## Active Folder Coordination

- Set a stable agent id per terminal before claim/check/commit.
- External agents (Codexc/Gemini):
  - `powershell: $env:AGENT_ID = "codexc"`
  - `powershell: $env:AGENT_ID = "gemini"`
- Thomas-native agents:
  - `powershell: $env:THOMAS_AGENT_ID = "codex-main"`
- Before editing, run:
  - `python scripts/active_folders.py check --path <target-folder>`
- Claim folder ownership while working:
  - `python scripts/active_folders.py claim --path <target-folder> --note "<task>"`
- Before implementation edits, pair folder claim with workboard bootstrap when not task-manager:
  - `python scripts/agent_bootstrap_claim.py --agent "$env:AGENT_ID" --scope "<paths>" --task "<short task>" --name "<alias>"`
- Commits auto-check staged files via pre-commit hook:
  - `python scripts/active_folders.py guard-staged --require-explicit-agent`
- Release after completion:
  - `python scripts/active_folders.py release --agent "$env:AGENT_ID"`
- Full guide: `docs/ops/ACTIVE_FOLDERS_COORDINATION.md`
