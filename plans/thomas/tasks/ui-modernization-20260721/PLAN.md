# UI-MODERNIZATION-20260721

Status: corrective implementation complete; ready for isolated owner testing, not approved for integration
Integration owner: `codex-ui-modernization`  
Base: `dev` at `cc6810463f1ca95970cd1175a4b19e2a4b5cfb95`

## Binding outcome

Modernize Mission Control, Virtual Office, Canvas, Library (the owner-facing name for `my_stuff`), Channels, Token Economy, Marketplace, and Settings against current Thomas Chat as a locked visual source of truth. Do not restyle or rearrange normal Chat. Match its exact tokens, spacing rhythm, type, density, eyes mark, controls, five themes, and motion language; load without the unrelated classic-runtime penalty where possible; and comply with `docs/UI_EDIT_MODE_STANDARD.md` and `docs/WORKSPACE_RESIDENT_SPECIALIST_STANDARD.md`.

## Shared integration first

1. Add one workspace shell for theme tokens, Thomas eyes identity, embedded/standalone behavior, and parent-child theme synchronization.
2. Add one UI Edit Mode runtime and one breakpoint-aware layout store. No route-specific editors.
3. Give every meaningful region a stable `data-ui-id`, owner-readable label, and safe component policy.
4. Replace avoidable full-classic route entry with bounded direct surfaces; parallelize any classic script path that remains.
5. Preserve live components and existing API wiring.
6. Provide one shared workspace Chat drawer, backed by a direct resident specialist per workspace. General Chat remains the task-manager coordinator; workspace residents never dispatch or delegate.

## Owner lanes

| Workspace | Owner lane | Product requirements | Edit Mode registration |
| --- | --- | --- | --- |
| Mission Control | `codex-ui-mission` | Real mission APIs, current Thomas shell, reduced cold start | Header/actions, run controls, status/queue panels; critical approval policy protected where needed |
| Virtual Office | `virtual_office` | Preserve agent presence, movement, map, chat, mission stream | Office canvas, agent/status panels, command/chat regions; map/item identity uses stable agent keys |
| Canvas | `canvas` | Rename owner-facing UI Editor to Canvas, retire competing renderers | Canvas toolbar, stage, inspector, preview; stable artifact/component keys |
| Library (`my_stuff`) | `codex-ui-my-stuff` | Direct dense app/file workspace, current themes and mark | Header/actions, filters, library groups/items with stable record keys |
| Channels | `channels` | Preserve Discord lifecycle, history, config, voice | Connection, channel/history, configuration panels; secret/destructive controls protected |
| Token Economy | `token_economy` | Bound animation/runtime work to the route and untangle global CSS | Summary, ledger, controls, visualization; policy controls constrained/protected |
| Marketplace | `marketplace` | Preserve canonical signed install/sync semantics | Search/filter, catalog/detail/install regions; stable package keys and protected install policy |
| Settings | `codex-ui-settings` | Native Thomas visual system with existing security behavior | Sections/cards/actions; secrets, break-glass, reset, and destructive controls protected |

Every owner brief includes the standing UI Edit Mode directive before implementation lands. Owners modify only claimed route files; shared shell, editor, version, changelog, and integration tests remain with the integration owner.

## Acceptance matrix

For all eight routes, capture deterministic desktop, tablet, and mobile evidence and assert:

- Thomas eyes identity and five-theme token response;
- useful first paint without unrelated workspace initialization;
- no console or failed-resource regressions in the exercised path;
- semantic editor registration for every meaningful region;
- moved real action still works after exiting Edit Mode;
- panel resize preserves controls/state;
- reload persistence and breakpoint isolation;
- action interception while editing;
- undo, reset, keyboard nudge/resize, Escape, and accessible focus.

## Release gate

- Focused route tests pass for each owner lane.
- Shared shell/editor contract tests pass.
- Architecture, boot, step-up, and release-hygiene gates pass in the isolated worktree.
- Browser proof is stored with route, viewport, theme, interaction, console, and resource results.
- Version and changelog describe the behavioral change.
- The original dirty Thomas checkout remains untouched.

## Completion evidence

This is the corrective replacement record. The first modernization checkpoint is superseded for readiness decisions. Integration remains deliberately blocked until the owner finishes live testing.

- Shared shell: all eight routes use the literal living Chat world and persistent model/theme top bar. Normal Chat still labels its action **Canvas**; every workspace labels it **Chat** and opens the shared right drawer. The hidden Chat welcome robot, cards, composer, and ordinary Canvas panel are inert beneath mounted tools.
- Resident specialists: Mission Control, Virtual Office, Canvas, Library, Channels, Token Economy, Marketplace, Settings, and the visible Paper Trading route receive isolated workspace histories and a bounded direct specialist. The workspace branch occurs before General Chat orchestration and cannot reach `send_task`, `update_task`, task-manager dispatch, delegation, Discord routing, or autopilot. Guarded mutations require a real receipt and authoritative readback.
- Route matrix: eight workspaces across Nebula, Dark, Light, Aurora, and Sandstone use one visible Chat world, transparent embedded canvases, normal color scheme, unique semantic editor identities, the correct resident identity, and no console, page, or non-abort request errors.
- Library: the marketing robot/hero was removed. The operational library uses 1,736px of the 1,768px content area and keeps canonical empty state honest instead of inventing artifacts.
- Marketplace: the live isolated profile classified 481 entries as 0 verified and 481 Potential. Potential initially renders 34 cards across four working shelves plus two editorial heroes, exposes zero false Install buttons, and remains outside GitHub as requested.
- Channels: the rejected 36-card icon wall is gone. The default view is a compact Discord-to-Thomas-to-Owner signal tool with live status, activity, refresh, and real Discord controls. Thirty-five unconfigured connections stay collapsed in a searchable planned catalog; a live Slack search returned exactly one result.
- Canvas and Token Economy: Canvas exposes Design, Draw, and a ready Three.js 3D fabrication viewport with GLTF/STL export, uses the shared resident drawer, and has no duplicate local conversation. Token Economy exposes five loaded operational panels in the current Chat theme with no legacy tint or loading placeholder.
- Virtual Office: the current 12-agent office map is canonical. Eight unreachable couch-heavy standalone bundles are removed, and the CLI roster now parses the same canonical agent seed source.
- UI Edit Mode: bare Ctrl+Shift, Ctrl+Shift+E, Shift+Tab, and Escape passed. A real Canvas action moved, was intercepted while editing, saved with Done & Save, opened Canvas afterward, and survived reload. A real composer resized without losing its descendants or typed state. Desktop/tablet isolation, undo/redo, reset, single-workspace editor chrome, keyboard operation, and accessible focus all passed.
- Stability: 40 repeated transitions across Channels, Marketplace, Token Economy, and Virtual Office retained a fixed two-frame pool and the same classic runtime. Outer resources stayed 25-to-25, measured JS heap stayed 18.2MB-to-18.2MB, switching averaged 338ms with a 693ms maximum, and the browser logged zero console, page, or non-abort request errors.
- Automated verification: 173 focused modernization/runtime tests and 16 step-up/release tests passed. Ruff, Python compilation, changed standalone JavaScript syntax, and `git diff --check` passed. The architecture suite passed 12 of 13; its one failure is unchanged pre-existing size debt in `thomas/core/llm_client.py` (804 lines), `thomas/server/chat_delegation.py` (808), and `thomas/server/chat_delegation_deliverable.py` (802), none of which is in this program.
- Runtime: `/api/health` reported version 0.19.1, protected mode, no degraded features, and `crash_count: 0`. Browser evidence lives under the corrective proof output; the implementation is local-only and has not been pushed or integrated.
