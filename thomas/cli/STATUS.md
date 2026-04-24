# Module: cli

| Field            | Value                                                    |
|------------------|----------------------------------------------------------|
| Status           | functional core, broad command surface partially verified |
| Last assessed    | 2026-04-24                                               |
| Used in prod     | yes, REPL and CLI commands are the terminal interface     |
| Has real tests   | partial                                                  |
| Blocking issues  | `repl.py` and `main_part02.py` exceed the size guideline  |

## What This Is

The command-line interface and interactive REPL for Thomas. It is the terminal
surface for chat, slash commands, tool approvals, session management, plan mode,
memory access, background tasks, setup, and server control.

The CLI is secondary to the web UI, but it should still feel like a polished
robot assistant instead of a throwaway developer tool.

## What Actually Works

- **REPL** (`repl.py` plus supporting files): interactive chat, streaming
  responses, tool approval flow, slash commands, keybindings, background tasks,
  plan mode, session management, memory commands, model settings, and project
  context.
- **Core commands** (`main.py`, `main_part01.py`, `main_part02.py`,
  `main_part03.py`): `thomas serve`, `thomas chat`, and basic subcommand
  routing.
- **Subcommand modules** (`commands/`): channels, companion, cron, evolve,
  investigate, quickstart, release, research, runs, sessions, setup wizard,
  shortcuts, telegram, training, updater, and webhooks. These exist, but not
  every command has been individually verified end-to-end.
- **Doctor** (`doctor.py`): diagnostics command exists and is part of the CLI
  surface.

## What Needs Verification

- Telegram, training, companion, cron, webhook, investigation, and shortcut
  commands may be partial or scaffolded.
- Non-interactive scripting, piped input/output, and git-aware operations need
  deeper verification before they should be called stable.
- Several helper modules (`sweep.py`, `scaffold.py`, `why.py`,
  `product_shell.py`, and `virtual_office_roster.py`) need ownership and
  status review.

## Target Capability Set

The CLI should support interactive streaming chat, tool use, slash commands,
session save/load/list, background task execution, plan mode, project context,
approval flow, memory management, model selection and failover, plugin/skill
management, one-shot mode, piped input/output, and scriptable automation.

## Architecture Issues

- `repl.py` is over the module size guideline and should eventually be split.
- `main_part02.py` is over the module size guideline and should eventually be
  split.
- The compatibility layer is several files of glue and could be consolidated
  once the command surface settles.

## Do Not Touch Without A Focused Refactor

- `repl.py` core event loop: this is the heart of the interactive experience.
- `main.py`: monolith loader entry point. Keep the load order stable unless the
  refactor explicitly covers it.
