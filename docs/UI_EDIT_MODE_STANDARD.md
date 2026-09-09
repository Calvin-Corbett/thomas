# Thomas UI Edit Mode Standard

Status: binding product and design-system standard  
Owner directive: UI-MODERNIZATION-20260721  
Effective: 2026-07-21

## Product promise

Every meaningful Thomas surface that is added or modernized participates in the shared UI Edit Mode. Editability is a property of Thomas's live components, not a screenshot builder and not a separate editor implemented per workspace.

The shared shell/editor runtime is the single implementation. Workspaces register their live regions with stable semantic identities and safe policies. Moving or resizing a region must preserve its event handlers, state, accessibility, and backend wiring.

## Locked Thomas visual source

Current Thomas Chat is the immutable visual source of truth for every workspace. Modernization copies Chat's exact five themes, color tokens, typography, spacing density, radii, control treatment, reduced-motion behavior, and square Thomas eyes mark; it does not reinterpret or redesign Chat. The eyes remain the Thomas identity at the top-left of each standalone workspace or its first meaningful workspace toolbar. Normal Chat receives no new visible editor control and no layout, spacing, type, color, control, or motion change. Edit Mode chrome exists only while an owner hotkey has invoked it.

## Component contract

Each meaningful editable region MUST provide:

- `data-ui-id`: stable semantic identity. Repeated records include a stable instance key, never a DOM index.
- `data-ui-label`: owner-readable name.
- `data-ui-policy`: supported operations and constraints. Critical controls use `protected` when editing would be unsafe.
- Minimum and maximum dimensions when the defaults are not appropriate.
- An intentional item or group registration policy for dynamic collections.

An editable component MUST remain the same live DOM component. Implementations MUST NOT replace it with a screenshot or duplicate its business logic. Ordinary component actions are intercepted only while Edit Mode is active.

## Shared capabilities

The shared runtime MUST provide:

- entry using bare `Ctrl+Shift`, `Ctrl+Shift+E`, or `Shift+Tab`; `Escape` exits;
- a movable slim toolbar, selection, drag, eight-way resize, keyboard nudge and keyboard resize;
- snapping and alignment guides, lock, undo, redo, reset, and layout export;
- separate desktop, tablet, and mobile layouts with durable local persistence;
- containment, minimum/maximum size, protected-control, and responsive fallback policies;
- accessible focus and keyboard operation.

## Save and recovery contract

- Entering Edit Mode starts a draft from the last saved layout for the current breakpoint.
- Moving, resizing, stacking, locking, undoing, and resetting update that draft immediately on screen, but do not replace the saved layout.
- **Done & Save** commits the draft and exits. **Cancel** or **Escape** exits and restores the last saved layout.
- **Previous** restores an earlier committed layout. Saved history is bounded and local to the workspace and breakpoint.
- **Export** downloads a portable copy; it does not save or commit the current draft.
- Covered regions remain recoverable through the semantic region picker, and front/back stacking never changes the component's live handlers or state.
- AI Edit sends the selected semantic component identity and owner prompt to the active surface's Thomas identity. Inside a workspace it opens that workspace's resident specialist; in normal Chat it remains with the generalist. Generated changes still require the normal governed implementation and proof flow.

## Safety rules

- A layout is keyed by workspace, semantic component identity, and breakpoint.
- Desktop, tablet, and mobile records never overwrite one another.
- Invalid or stale records fail safely to the authored responsive layout.
- Selection, dragging, and resizing clamp to the registered container.
- Secrets, break-glass controls, destructive actions, and required navigation may be protected.
- Removing or renaming a registered identity requires an explicit migration or reset path.

## Acceptance gate

A UI module is incomplete until its meaningful regions register with this contract and automated plus browser evidence proves:

1. A real actionable control can move, Edit Mode can exit, and the control still performs its action.
2. A real panel can resize without losing its controls or state.
3. The changed layout survives reload.
4. Desktop, tablet, and mobile layouts do not corrupt one another.
5. Edit Mode prevents accidental underlying actions.
6. Undo, reset, keyboard operation, and accessible focus work.
7. Every modernized workspace is covered by the route matrix, including Library (the owner-facing name for the internal `my_stuff` route).

The reference studio at `outputs/thomas-ui-studio` is working design evidence. Thomas's shared shell and real APIs remain authoritative when implementation details differ.
