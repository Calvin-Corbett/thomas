# Migration note: workspace.rbac_multi_tenant

This feature introduces multi-workspace tenancy with RBAC and strict isolation.

## Existing single-workspace installs

Running:

- `python -m server.workspace.migrate_schema`

will create a default workspace:

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
