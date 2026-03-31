# Claude Instructions for Thomas

Read AGENTS.md immediately. Every rule in that file applies to you.

## Claude-specific rules

- You MUST tag every commit with `Thomas-Agent: claude` in the commit message trailer.
- You MUST run the agent startup router before doing any work:
  `python scripts/agent_startup_router.py --summary "<task summary>"`
- You MUST NOT create files matching `*_part*.py` or `*.part*.py`. This is a monolith split pattern that is banned. If a file is too large, refactor it into separate modules with normal Python imports.
- You MUST NOT use `exec()` to load code from other files. Use normal imports.
- You MUST NOT modify any file listed in `agent_safety.toml` under `[protected_files]` without explicit user approval.
- You MUST NOT commit with `--no-verify`. Pre-commit hooks exist for a reason.
- You MUST run `ruff check` on any Python file you modify before committing.

## What Thomas is

Thomas is an AI-first workspace platform with a marketplace of domain modules. The repo is intentionally broad in scope — that is a feature, not a problem. Do not suggest removing, consolidating, or refactoring domain modules (e.g. `thomas/agriculture/`, `thomas/blockchain/`, etc.) unless the user explicitly asks you to.

## Architecture in 30 seconds

- `thomas/agent/` — Chat dispatch and agent loop. Casual messages get fast replies, actionable messages get dispatched to the task manager.
- `thomas/core/` — Config, persistence, token economy, LLM clients. This is the bottom of the dependency tree. It MUST NOT import from `thomas/server/` or `thomas/tools/`.
- `thomas/server/` — aiohttp web app, routes, web UI.
- `thomas/cli/` — CLI and REPL.
- `thomas/tools/` — Tool definitions and registry.
- `thomas/memory/` — Conversation and context stores.
- Everything else under `thomas/` — Marketplace domain modules. Leave them alone unless told otherwise.

## Branch awareness (required — prevents duplicate work)

Before creating ANY new file or feature, check for existing work on other branches:

```bash
git branch -a --list '*<keyword>*'          # branches named after the feature
git log --all --oneline --grep='<keyword>'  # commits mentioning it anywhere
```

Replace `<keyword>` with the core noun of your task (e.g., `channel`, `discord`, `voice`, `marketplace`).

If you find matching branches or commits:
1. Read the diff: `git log --oneline master..<branch>` to see what was done.
2. Ask the user before building anything new — the work may just need a merge.
3. If the branch has real, working code, merge or cherry-pick it instead of rewriting.

The startup router (`agent_startup_router.py`) now scans branches automatically and will warn you. **Do not ignore branch scan warnings.**

## Before you write code

1. Read `AGENTS.md` (full rules and router startup)
2. Read `GUARDRAILS.md` (immutable project rules)
3. Read the module-level `GUARDRAILS.md` in whatever directory you're modifying (if one exists)
4. Check `agent_safety.toml` for protected files, forbidden patterns, and circular import rules
