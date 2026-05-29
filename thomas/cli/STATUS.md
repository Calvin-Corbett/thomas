# Module: cli

| Field            | Value                                                   |
|------------------|---------------------------------------------------------|
| Status           | functional (REPL works, many commands exist, gaps below)|
| Last assessed    | 2026-03-18                                              |
| Assessed by      | claude-opus-4-6 (Cowork session) + the product owner|
| Used in prod     | yes — REPL and CLI commands are the terminal interface   |
| Has real tests   | partial                                                  |
| Blocking issues  | repl.py over 800-line limit (1806 lines)                 |

## What This Is

The command-line interface and interactive REPL for Thomas. This is how you
talk to Thomas in a terminal. 49,000 lines across 232 files.

**Important: this module is secondary to the web UI**, but it was intentionally
developed to have personality and polish. It's not a throwaway dev tool.

## Product Vision (from the product owner, 2026-03-18)

- The CLI is **secondary to the web UI** but should still be good
- **Feature parity with Claude Code and Codex is the target.** Thomas's CLI
  should do everything those tools do. This is not about competing — it's
  about being complete. If Claude Code can do it, Thomas should be able to too.
- The CLI should have **flavor** — it's not a dry developer tool. It should
  feel like interacting with your robot assistant, same as the web UI.

## What Actually Works (verified)

- **REPL** (`repl.py` + 14 supporting files): Interactive chat in the terminal.
  Uses prompt_toolkit for input and rich for output. Streaming responses,
  tool approval flow, slash commands, keybindings, background tasks, plan mode,
  session management. This is real and actively used.
- **Core CLI commands** (`main.py` → `main_part01-03.py`): `thomas serve`,
  `thomas chat`, basic subcommand routing. Works.
- **Subcommands** (`commands/` — 17 files): channels, companion, cron, evolve,
  investigate, quickstart, release, research, runs, sessions, setup_wizard,
  shortcuts, telegram, training, updater, webhooks. **These exist as files
  but have NOT been individually verified.** Some may be scaffold.
- **Doctor** (`doctor.py`): Diagnostics command. Exists, not fully assessed.
- **Recent REPL UX work** (0.14.37): Ephemeral input, accent theming,
  live activity feeds, panel toggles, mascot styling, reasoning picker.
  These were recently developed and appear functional.

## What Has NOT Been Verified

**WARNING: The presence of a file does NOT mean it works.** The following
exist as code but have not been assessed for whether they actually function:

- `commands/telegram.py` — Telegram bot integration. May be scaffold.
- `commands/training.py` — Training system. May be scaffold.
- `commands/companion.py` — Companion device commands. May be scaffold.
- `commands/cron.py` — Cron/scheduled tasks. May be scaffold.
- `commands/webhooks.py` — Webhook management. May be scaffold.
- `commands/investigate.py` — Investigation workflow. May be scaffold.
- `commands/shortcuts.py` — Shortcut system. May be scaffold.
- `sweep.py` — Unknown purpose. Not assessed.
- `scaffold.py` — Literally named "scaffold." Not assessed.
- `why.py` — Unknown purpose. Not assessed.
- `product_shell.py` — Unknown purpose. Not assessed.
- `virtual_office_roster.py` — Virtual office from CLI. Not assessed.

## What Should Exist (full vision, NOT yet verified as working)

To reach feature parity with Claude Code / Codex, the CLI should support:
1. Interactive streaming chat with tool use (EXISTS — REPL)
2. Slash commands for common operations (EXISTS — repl_slash.py)
3. Session save/load/list (EXISTS — repl_state.py, commands/sessions.py)
4. Background task execution (EXISTS — repl_background.py)
5. Plan mode / multi-step reasoning (EXISTS — repl_plan.py)
6. Project context awareness (EXISTS — repl_project.py)
7. Approval flow for sensitive actions (EXISTS — repl_approval.py)
8. Memory query and management (EXISTS in REPL via /memory command)
9. Model selection and failover (EXISTS in REPL settings)
10. Plugin/skill management from CLI (PARTIAL — repl_skills.py)
11. Non-interactive single-shot mode (NEEDS VERIFICATION)
12. Piped input/output for scripting (NEEDS VERIFICATION)
13. Git-aware operations (NEEDS VERIFICATION)

## Parity / Compatibility Layer

~10 files (`parity_*.py`, `compat_*.py`) exist to make Thomas CLI commands
match the interface of a competing product. These provide command-name
aliases and argument translation.

**PRE-PUBLIC CLEANUP REQUIRED:** These files contain direct competitor
references that must be scrubbed before the repo goes public. See the
cleanup tracking note in the repo. The parity goal is still important —
the files should be refactored to describe the TARGET feature set without
naming the competitor.

## Architecture Issues

- `repl.py` is **1,806 lines** — more than 2x the 800-line limit. Needs split.
- `main_part02.py` is 1,044 lines — over limit. Needs split.
- The parity/compat layer is ~10 files of glue. Could potentially be
  consolidated or absorbed into the main command structure.
- 232 files total is a lot. Some may be dead code.

## Known Gaps

- repl.py over size limit (1806 lines)
- main_part02.py over size limit (1044 lines)
- Many subcommands not verified as functional
- Competitor references throughout parity/compat files (pre-public blocker)
- No STATUS.md existed before this one (added 2026-03-18)

## Do Not Touch

- `repl.py` core event loop — this is the heart of the interactive experience.
  Refactoring is needed (split the file) but don't change the behavior
  without explicit user approval.
- `main.py` — monolith loader entry point. Don't restructure the load order.
