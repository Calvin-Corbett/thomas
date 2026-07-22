# Thomas Workspace Resident Specialist Standard

Status: binding product and runtime standard  
Owner directive: UI-MODERNIZATION-20260721  
Effective: 2026-07-21

## Product promise

Every Thomas workspace has a resident Thomas specialist that works directly in that workspace. The specialist is not a thin entry point to General Chat, a task-manager dispatcher, or a background delegation queue. General Chat remains the cross-domain generalist and coordinator; a workspace resident stays inside its named domain and uses that workspace's real capabilities.

The top-bar **Chat** action and right-side drawer are one shared visual shell. The visible shell, scoped history, and composer are reused across workspaces, while the server selects the specialist contract from the canonical workspace identity.

## Runtime contract

- Workspace turns use `surface_mode="workspace"` and a canonical `context_id="workspace:<route>"`.
- Histories are isolated by workspace context. A Virtual Office conversation never appears in Channels, Library, or General Chat.
- The resident runtime exposes one server-owned `operate_workspace` tool whose action vocabulary is allowlisted for the active workspace.
- General orchestration tools, `send_task`, `update_task`, task-manager dispatch, delegation events, and autopilot handoff are unreachable from the workspace branch.
- Each visible workspace provides at least one real, safe action in addition to inspection. Read-only inspection cannot be its only capability.
- The client never supplies arbitrary tool names, URLs, filesystem paths, or registry capabilities. It asks in natural language; the server chooses from the active workspace's bounded action schema.
- Mutations pass through the normal Thomas policy/guardrail boundary and are followed by authoritative readback. A resident may claim success only when the receipt and readback prove it.
- Missing capabilities fail honestly in the current workspace. The resident does not pretend to have dispatched work elsewhere.
- Virtual Office direct actions mutate the shared `/api/office/state` store and hydrate the mounted Office immediately; they never queue Mission Control work as a substitute for Office work.
- Settings and Token Economy bind to the typed `PreferencesStore` fields used by `/api/preferences`, scoped to the requesting user. The local-storage Thomas shell theme is not exposed as a resident setting until it has a deliberate shared-state bridge.

## Shared drawer contract

- The top action reads **Canvas** only in normal Chat. In a workspace it reads **Chat** and opens the shared drawer without unmounting the workspace.
- The drawer presents the current workspace's resident identity, scoped session list, conversation, and composer.
- Switching workspaces cancels any in-flight drawer turn, clears transient state, and loads only the target workspace's history.
- Canvas, Library, and all other workspaces use this shared drawer. Route-local duplicate chat composers and direct General Chat bridges are retired.
- The drawer inherits the literal Thomas Chat theme tokens and participates in the shared UI Edit Mode contract with protected critical controls.

## Acceptance gate

A workspace chat implementation is incomplete until automated and browser evidence proves:

1. the workspace remains mounted while its drawer opens and closes;
2. the outgoing request carries the exact workspace namespace;
3. history remains isolated between at least two workspace contexts and General Chat;
4. the workspace branch exposes no general dispatch or task-manager tools;
5. one real workspace action executes through policy and authoritative readback;
6. cross-workspace actions are rejected;
7. a failed or unavailable mutation is reported without a false success claim;
8. duplicate route-local chat paths are absent; and
9. UI Edit Mode intercepts drawer actions safely without corrupting the resident session.
