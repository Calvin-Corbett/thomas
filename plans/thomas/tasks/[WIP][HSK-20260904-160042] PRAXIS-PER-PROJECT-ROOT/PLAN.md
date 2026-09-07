# PLAN for [WIP][HSK-20260904-160042] PRAXIS-PER-PROJECT-ROOT

- Owner: claude
- Status: in_progress
- Updated At: 2026-09-04T16:25:02+00:00
- Scope: thomas/core/project_root.py,thomas/core/praxis_scaffold.py,thomas/core/task_bot_runtime.py,thomas/agent/chat_dispatcher.py,thomas/server/chat_delegation_session.py,tests/test_praxis_roots_at_the_project.py,CHANGELOG.md,thomas/server/chat_delegation.py,thomas/server/chat_delegation_workspace.py,thomas/core/agent_presence.py,thomas/agent/instruction_resolution.py,plans/thomas/tasks/[WIP][HSK-20260904-160042] PRAXIS-PER-PROJECT-ROOT

## Summary

Praxis (workboard, claims, presence, executions) roots itself at the Thomas
checkout it was imported from, never at the project the work is about. You
described the intended design on 2026-09-04: "You're supposed to start a new
project and build your own new work board ... it's like setting up the
environment ... that's what he has to do is make that work board." This task
makes the coordination root follow the project, and scaffolds that project's
own board on first use.

## Evidence (verified 2026-09-04)

- `thomas/core/agent_presence.py:23` `ROOT = Path(__file__).resolve().parents[2]`;
  `coordination_dir`, `presence_dir`, `default_workboard_path`
  (`plans/thomas/WORKBOARD.md`) all hang off it.
- `thomas/core/task_bot_runtime.py:38-52` the same binding, a second copy.
- `thomas/agent/chat_dispatcher.py:27-29` `_ROOT`, `_DEFAULT_WORKBOARD`;
  `_add_task_to_workboard` mirrors every chat task onto Thomas's own board.
  When the board is absent it does `log.error(...); return False` and the task
  runs anyway - coordination silently vanishes off-repo.
- `thomas/server/chat_delegation.py:75` `ROOT = Path(__file__)...`; its
  `_resolve_repo_root(repo_root)` defaults to it, so the one caller that passes
  `repo_root=root` to `dispatch_async` passes Thomas's install root. The worker's
  real folder exists as `work_dir` (line ~719) but is only used for instructions.
- Off-repo effect: the Terminal-Bench `broken-python` transcript contains zero
  board-related lines; the `regex-chess` container had no WORKBOARD.md anywhere.
- On-repo effect: `plans/thomas/tasks/` holds five identical `[WIP][HSK-...] LAND-THREE`
  dirs and five `... a dispatch returns what Claude said` - every bootstrap of
  every session mints a new task on the one board under the one name `claude`.
- Two project-root finders already exist and are NOT duplicates:
  `thomas/agent/instruction_resolution.py:98 find_project_root` (nearest `.git`
  - a project's root) and `thomas/forge/anvil/doppelganger.py:121` (nearest
  `pyproject.toml` + `thomas/` - Thomas's own root). The first is the one Praxis
  needs.

## Approach

Status 2026-09-04: steps 1-5 landed (77175762); step 6 landed next (one-offs coordinate at the
user's own board in the data dir via `coordination_root`; a folder with no repo is its own root).
Step 7 landed (boards index route). Remaining: `agent_presence` (waiting
behind the other session's split; zero-growth waiver).

1. `thomas/core/project_root.py` - one resolver: explicit arg > `THOMAS_PROJECT_ROOT`
   env > `find_project_root(cwd)` from instruction_resolution > cwd. Thomas's own
   checkout is just one possible answer, not the default.
2. `agent_presence.resolve_repo_root(None)` and `task_bot_runtime.coordination_dir(None)`
   resolve through it instead of `ROOT`. `ROOT` stays only as the install location.
3. `thomas/core/praxis_scaffold.py` - `ensure_praxis(project_root)` creates
   `plans/<project-name>/WORKBOARD.md` (from a template carrying the sections the
   scripts require: Execution Status, Problem Traceability, Agent Claims, Active
   Tasks, Up For Grabs, Issues / Blockers, Task Problems, Agent Message Traffic,
   Task Plans, Inactive Agents) and `runtime/coordination/` on first use. Called
   from the dispatcher and delegation before any board write.
4. `chat_dispatcher._add_task_to_workboard`: the absent-board branch calls
   `ensure_praxis` and proceeds; it no longer logs an error and drops coordination.
5. `chat_delegation` passes `find_project_root(work_dir)` as `repo_root`, not `ROOT`.
6. Not every job is a repo. You said so on 2026-09-04: "the workboard isn't just repo
   stuff, it's tasks Thomas does for the user ... this project, his own repo, making a
   simple PDF, but those projects aren't all the same." Rule: the coordination root is
   the job's working folder, whatever the job is - the git root for repo work, the
   per-task folder Code mode already creates for a one-off (a PDF, a note), Thomas's
   own checkout for Thomas work. `find_project_root` must NOT walk past a task folder
   to the home directory; a folder with no `.git` is its own root.
7. One user-level index across all of it: `thomas/server/routes/local_projects_helpers`
   already keeps a registry of projects with `root_path` and `kind` (repos and
   generated deliverables alike). A registry entry owns the board at its `root_path`;
   "what is Thomas doing for me" reads the registry and each board - not one giant
   shared board.
8. Identity per session on the board (the `claude` collision) is a separate task;
   this one removes cross-project collision by giving each project its own board.

## Tests (write first)

- Dispatching a task with cwd inside a temp git project creates
  `<project>/plans/<name>/WORKBOARD.md` and writes the task there; Thomas's own
  `plans/thomas/WORKBOARD.md` is byte-identical before and after.
- With `THOMAS_PROJECT_ROOT` set, presence and executions land under it.
- An installed (tarball) Thomas with no checkout still gets a board in the
  project - the container case.
- `ensure_praxis` is idempotent and never overwrites an existing board.

## Risks / sequencing

- `thomas/core/agent_presence.py` is 1258 lines with a `max_growth_lines: 0`
  waiver, and carries another session's uncommitted split to
  `agent_presence_sessions.py` (takes it to 1149). Land or park that split first;
  this task's edits there must be net-zero or wait behind it.
- `chat_delegation.py` / `chat_dispatcher.py` are hub files; keep edits to the
  root resolution lines and the absent-board branch only.
- Scripts under `scripts/crew/` and `scripts/forge/gates/` also assume the Thomas
  root (`--workboard` default `plans/thomas/WORKBOARD.md`); they are out of scope
  here and keep working for Thomas's own repo unchanged.
