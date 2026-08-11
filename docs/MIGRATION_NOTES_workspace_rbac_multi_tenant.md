# Migration note: workspace.rbac_multi_tenant

This feature introduces multi-workspace tenancy with RBAC and strict isolation.

## Existing single-workspace installs

**No migration command is needed, and the one this document used to name never
worked.** Corrected 2026-08-11.

This said to run `python -m server.workspace.migrate_schema`. That module lived
in a second `server/` package at the repository root -- a FastAPI + SQLAlchemy
stack that duplicated the workspace system and **could not be imported at all**
(`server/workspace/models.py` did `from server.db.base import Base`, and
`server/db/` did not exist). That package has been removed.

The workspace system that actually ships is `thomas/server/workspace/`, and it
provisions its own schema: `db.py::ensure_schema()` issues
`CREATE TABLE IF NOT EXISTS` for `workspaces`, `workspace_memberships` and
`workspace_invites` on use. An existing single-workspace install gets a default
workspace with no operator action:

- `workspace_id`: `00000000-0000-0000-0000-000000000001`
- `name`: `Personal`
- `owner_user_id`: first user found (best-effort)

It then backfills `workspace_id` on existing rows in known tables (sessions/chats/memory/jobs/tokens) *if those tables exist*.

## Client behavior

Clients should send:

- Header: `X-Workspace-Id: <workspace_id>`

The web UI switcher stores the current workspace id in `localStorage` under:

- `thomas.currentWorkspaceId`

The feature pack includes a global fetch shim that automatically injects `X-Workspace-Id`
for same-origin `/api` calls.
