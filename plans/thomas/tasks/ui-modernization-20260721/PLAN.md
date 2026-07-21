# UI-MODERNIZATION-20260721

Status: complete  
Integration owner: `codex-ui-modernization`  
Base: `dev` at `cc6810463f1ca95970cd1175a4b19e2a4b5cfb95`

## Binding outcome

Modernize Mission Control, Virtual Office, Canvas, My Stuff, Channels, Token Economy, Marketplace, and Settings against current Thomas Chat as a locked visual source of truth. Do not restyle or rearrange normal Chat. Match its exact tokens, spacing rhythm, type, density, eyes mark, controls, five themes, and motion language; load without the unrelated classic-runtime penalty where possible; and comply with `docs/UI_EDIT_MODE_STANDARD.md`.

## Shared integration first

1. Add one workspace shell for theme tokens, Thomas eyes identity, embedded/standalone behavior, and parent-child theme synchronization.
2. Add one UI Edit Mode runtime and one breakpoint-aware layout store. No route-specific editors.
3. Give every meaningful region a stable `data-ui-id`, owner-readable label, and safe component policy.
4. Replace avoidable full-classic route entry with bounded direct surfaces; parallelize any classic script path that remains.
5. Preserve live components and existing API wiring.

## Owner lanes

| Workspace | Owner lane | Product requirements | Edit Mode registration |
| --- | --- | --- | --- |
| Mission Control | `codex-ui-mission` | Real mission APIs, current Thomas shell, reduced cold start | Header/actions, run controls, status/queue panels; critical approval policy protected where needed |
| Virtual Office | `virtual_office` | Preserve agent presence, movement, map, chat, mission stream | Office canvas, agent/status panels, command/chat regions; map/item identity uses stable agent keys |
| Canvas | `canvas` | Rename owner-facing UI Editor to Canvas, retire competing renderers | Canvas toolbar, stage, inspector, preview; stable artifact/component keys |
| My Stuff | `codex-ui-my-stuff` | Direct lightweight library, current themes and mark | Header/actions, filters, library groups/items with stable record keys |
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

- Normal Chat: deterministic 1440-by-1000 baseline comparison after the requested Canvas rename changed 0 of 1,440,000 pixels; both captures had zero console/page errors.
- Route matrix: all eight routes matched Chat's exact Nebula, Dark, Light, Aurora, and Sandstone background/accent/card-radius/label-font contract; visible semantic identities were unique; Edit Mode remained hidden in normal use and entered/exited from the keyboard with accessible focus; stable browser state logged no console/page errors.
- Identity: the shared mark computes to 30-by-30 pixels, 9px radius, no border, Chat's 18px glow, and two 5-by-6 eyes; route-local geometry overrides were removed.
- Live editing: Token Economy's real Refresh control moved 48px, was prevented from firing during Edit Mode, fired after exit, reloaded at the persisted position, and still fired after reload.
- Safe layout: desktop, tablet, and mobile maps remained isolated; lock, keyboard nudge/resize, undo, reset, bare Ctrl+Shift, Ctrl+Shift+E, Shift+Tab, and Escape passed.
- State preservation: the Settings agent panel resized from 920x272 to 992x320 while retaining all 34 descendants and the live input value; all eight handles were available.
- Startup: Mission Control, My Stuff, and Settings reached their visible direct surfaces in 474ms, 457ms, and 615ms in the proof run with no classic loader. Canvas's remaining 96 split runtime files began within a 19.5ms window and its surface was visible in 2.112s.
- Automated verification: 130 focused modernization/runtime tests passed; step-up protocol passed 5 tests; JavaScript syntax and `git diff --check` passed. The architecture suite passed 12 of 13 and remains blocked only by three pre-existing out-of-scope Python size debts (`llm_client.py`, `chat_delegation.py`, `chat_delegation_deliverable.py`).
