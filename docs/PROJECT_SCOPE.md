# Thomas Project Scope

Thomas is a local-first AI workspace for chat, tools, memory, automation, and
operator workflows. The public release is scoped around helping a user run a
private assistant on their own machine first, then opt into integrations or
remote deployment only when they understand the security posture.

## Product Priorities

1. Start reliably on Windows from `run-ui.cmd`.
2. Keep the default runtime local to `127.0.0.1`.
3. Make model setup, repair, and diagnostics understandable to non-engineers.
4. Provide guarded tool execution with visible approvals and audit trails.
5. Surface automation, memory, workflows, and integrations without requiring a
   user to understand the whole codebase.

## Public Release Boundaries

- Public releases must not include private research notes, old launch
  scoreboards, personal handoff logs, local test-output archives, or private web
  deployment instructions.
- Public releases should document product capabilities and limitations in
  `docs/FUNCTIONALITY_INVENTORY.md`.
- Public releases should keep development automation that protects the project,
  but remove stale artifacts that only describe historical private work.

## Non-Goals For The First Public Snapshot

- No hosted SaaS promise.
- No default LAN or public internet binding.
- No claim that every marketplace/scaffold module is production complete.
- No private website deployment surface in the public runtime branch.
