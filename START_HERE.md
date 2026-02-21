# Start Here (Thomas)

If you are not technical, use this file first.

## Daily Use

1. Double-click `run-ui.cmd`.
2. Open `http://127.0.0.1:8899` if browser does not open.
3. If setup fails, run `repair.cmd`.

## What This Project Tracks

- The only active Git repo is now `F:\DevHub\Thomas`.
- Parent folder `F:\DevHub` is no longer an active repo.

## For Any New Agent

1. Read `AGENTS.md`.
2. Read `docs/ops/NEXT_AGENT_HANDOFF.md`.
3. Read latest section in `docs/ops/agent_handoff_log.md`.
4. Run `python scripts/auto_checks.py --quick`.

## If Something Feels Broken

1. Run `python scripts/auto_checks.py --quick`.
2. Run `python -m thomas doctor --full`.
3. Ask the agent to append a timestamped note to `docs/ops/agent_handoff_log.md` before stopping.