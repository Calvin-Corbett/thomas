# Scopes (Working On Parts Of Thomas)

As Thomas grows, changes should be scoped to a subsystem to reduce risk and improve iteration speed.

Suggested scopes:
- `ui`: `thomas/server/web/**`
- `server`: `thomas/server/**`
- `agent`: `thomas/agent/**`, `thomas/core/**`
- `tools`: `thomas/tools/**`
- `memory`: `thomas/memory/**`, `runtime/**` (data formats only)
- `cli`: `thomas/cli/**`, `scripts/**`
- `models`: `thomas/models/**`, `thomas/server/web/models.json`
- `docs`: `README.md`, `CHANGELOG.md`, `SOUL.md`, `definitions/**`

Scoping rules:
- Make the smallest change that solves the problem.
- Prefer local refactors (within scope) over cross-cutting rewrites.
- If you must cross scopes, explicitly list the call path you are changing and why.

