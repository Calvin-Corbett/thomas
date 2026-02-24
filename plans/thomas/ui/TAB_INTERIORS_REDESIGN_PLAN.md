# Thomas Tab Interiors Redesign Plan

Status: draft  
Owner: Thomas Web UI  
Last updated: 2026-02-22  
Canonical path: `plans/thomas/ui/TAB_INTERIORS_REDESIGN_PLAN.md`

## Objective
Replace the current generic, repeated tab layouts with purpose-built interiors for every Thomas tab, while keeping the existing app shell unchanged in this phase.

## Scope Lock (This Phase)
In scope:
- Everything inside tab content areas.
- Tab-specific layouts, modules, labels, actions, and data wiring.
- Removal of seeded/demo data from tab interiors.
- Live refresh behavior for tab data (no manual refresh controls as primary UX).

Out of scope:
- Global left sidebar structure/width behavior.
- Global top bar and bottom status bar redesign.
- Global shell/right inspector architecture changes.
- Route/table naming changes outside tab internals.

## Non-Negotiable UX Rules
1. No seeded or fake data rendered in production paths.
2. Each tab must have a distinct layout pattern (no cloned card grids everywhere).
3. Live updates by default via SSE/WebSocket or polling fallback.
4. Long streams use paging/virtualized windows, never unbounded infinite lists.
5. Risky actions require explicit confirmation with exact target preview.
6. Every action logs to Timeline with actor, target, result, and rollback status.

## Shared Interior Patterns
- Pattern A: Tri-pane list/detail for Inbox, People, Finance, Integrations, Timeline.
- Pattern B: Canvas builder for Automations, App Builder.
- Pattern C: Media/editor workspace for Studio, Game Studio, 3D Lab, Dev Studio.
- Pattern D: Monitoring console for Mission Control.
- Pattern E: Workspace hub for Dashboard, Virtual Office, Operations, Research Lab.

## Cross-Tab Safety Baseline
- Action levels shown everywhere: `Read-only`, `Assisted`, `Auto`.
- Any send/pay/deploy/delete action opens a confirmation drawer with:
  - exact targets
  - effect summary
  - rollback/undo status
  - `Require approval next time` option
- All approvals and denials are emitted to Timeline.

## Naming Cleanup
Use consistent user-facing names:
1. Dashboard
2. Chat
3. Virtual Office
4. Operations
5. Inbox
6. Notifications Center
7. Automations
8. Agents
9. Mission Control
10. Studio
11. Content Hub
12. Dev Studio
13. App Builder
14. Game Studio
15. 3D Lab
16. Research Lab
17. People
18. Finance
19. Integrations
20. Marketplace
21. Vault
22. Timeline
23. Infinite

## Tab Interior Specs

### 1) Dashboard (Pattern E)
- Modules: Now card, Alerts card, Inbox pulse, Today timeline, Robot feed, Pinned projects, Recent activity.
- Priority order: urgent alerts, due tasks, near-term calendar, workflow failures.
- Action shortcuts: Start Focus, Triage Inbox, View Incident, Morning Brief.

### 2) Chat (Pattern A + composer actions)
- Left: workspace-grouped conversation list and search.
- Center: transcript + composer with `+` button action menu.
- `+` menu options: Research, Create Image, Create Video, Create Song, Add Files, Games.
- Selecting an option adds a removable mode chip in chat (left-side bubble with `x`).
- Games submenu opens to the right of the action menu.
- First game: Cloud Jump side panel on right, robot runner, falling platforms, score + persistent high score.

### 3) Virtual Office (Pattern E)
- Subviews: My Day, Tasks, Calendar, Notes, Files, Projects, Briefings.
- Key modules: time blocks, top outcomes, priority scoring, quick capture, daily brief thread.
- Auto-suggested scheduling and follow-up reminders.

### 4) Operations (Pattern E)
- Subviews: Overview, Customers, Sales/Orders, Inventory, Team Scheduling, Analytics, Disputes.
- Top-first modules: today queue, exception queue, revenue/churn/open-order KPI strip.
- Always include direct tasking and escalation actions.

### 5) Inbox (Pattern A)
- Unified account folders + triage buckets.
- Center list shows sender, subject, one-line summary, class confidence.
- Right pane actions: Summarize, Draft Reply, Next Steps, Create Task, Schedule Follow-up.
- Commitment extraction to task items with source links.

### 6) Notifications Center (Pattern A)
- Left: channels, categories, robot profiles.
- Center: grouped timeline with severity filters and bundle controls.
- Right: rules editor (quiet hours, batching, escalation, re-ping policies).

### 7) Automations (Pattern B)
- Palette: triggers, logic, actions, approvals, retry/backoff.
- Canvas: drag/drop workflow graph with minimap.
- Right properties and bottom run logs with node-level IO/error detail.

### 8) Agents (Pattern A)
- Agent roster with status and group.
- Agent detail: role, goals, tools, memory scope, assignment queue.
- Guardrails: blocked actions/domains, spend limits, dry-run simulation.

### 9) Mission Control (Pattern D)
- Remove top marquee/scrolling active-items banner.
- Top: environment selector + health strip (uptime, errors, latency, queue depth).
- Center-left: dashboards/log stream with filter + bounded window.
- Center-right: incidents panel and runbook quick actions.
- Required task/cron management modules:
  - scheduled tasks list with search/filter
  - cron jobs list with `next run`, `last run`, `owner`, `status`
  - add/edit task and add/edit cron job drawers
  - manual run and disable/enable controls
- Recent signals/events must be paged or virtualized and capped per view.
- Auto-live refresh enabled by default (no manual refresh buttons as primary flow).

### 10) Studio (Pattern C)
- Modes: Video, Audio, Design, Assets, Render Queue.
- Includes timeline editing, inspector tools, AI assist cluster, and render job tracking.

### 11) Content Hub (Pattern E)
- Calendar-first planning, library, campaigns, publishing, analytics, templates.
- Priority order: upcoming publish deadlines, blocked approvals, underperforming campaigns.

### 12) Dev Studio (Pattern C)
- Repo/issues/PR/build workspace.
- Center editor + diff + tests; right Thomas dev actions and risk notes; bottom terminal/logs.

### 13) App Builder (Pattern B)
- UI components + logic/data palette, responsive canvas, data binding inspector, run/error logs.

### 14) Game Studio (Pattern C variant)
- Project hub + per-project areas: assets, worlds, systems, builds, playtests.
- Engine connector controls and build/playtest pipelines.

### 15) 3D Lab (Pattern C variant)
- 3D viewport, model/material library, object inspector, non-destructive edit history, print queue.

### 16) Research Lab (Pattern E)
- Collection list, source/doc split reader, citation manager, notes outline, synthesis action.
- Includes claim table with supporting/counter sources and confidence.

### 17) People (Pattern A)
- Segments/tags, relationship timeline, commitments, reminders, check-in drafting.

### 18) Finance (Pattern A)
- Accounts/budgets/invoices/subscriptions/reports.
- Transactions grid + insights + approval queue.
- Forecast and anomaly modules placed high in the right panel.

### 19) Integrations (Pattern A)
- Installed/available connector catalog with scope and health visibility.
- Detail panel: permissions, mapping, reconnect, logs, bridge status.

### 20) Marketplace (Catalog)
- Search/filter storefront for templates/packs.
- Detail page: what installs, required permissions, dry-run simulation.

### 21) Vault (Admin console)
- Secrets, permission matrix, memory controls, data source boundaries, retention/backups.
- High-risk controls require double confirmation and audit events.

### 22) Timeline (Pattern A)
- Filtered action ledger by tab/integration/agent/workflow/severity.
- Detail pane shows IO, approvals, retries, rollback status, related chain.

### 23) Infinite (Device manager)
- Device pairing/state, routing preferences, quick capture pipelines, remote approvals, offline queue.

## Plugin and Download Surface (Captured for Build)
1. SaaS connectors: email, calendar, storage, social, git/CI, finance/accounting.
2. Desktop bridge: local files/app control/screenshot/log hooks within user-approved scope.
3. Engine plugins: Unreal, Unity, Godot.
4. Device adapters: printers, hubs, cast targets, vehicle APIs where available.
5. Template packs: workflows, agents, studio presets, app blueprints.

## Delivery Phases

### Phase 1: De-genericize Existing Core Tabs
- Tabs: Dashboard, Chat, Virtual Office, Operations, Inbox, Mission Control.
- Exit criteria:
  - distinct layouts live
  - no seeded data
  - live refresh and bounded streams enabled
  - mission control task/cron management present

### Phase 2: Control Plane and Trust Tabs
- Tabs: Notifications Center, Automations, Agents, Integrations, Vault, Timeline.
- Exit criteria:
  - safety baseline fully wired
  - permission/action auditing complete

### Phase 3: Build and Create Tabs
- Tabs: Studio, Content Hub, Dev Studio, App Builder, Game Studio, 3D Lab, Research Lab.
- Exit criteria:
  - editor/canvas patterns implemented per tab
  - plugin hooks represented and testable

### Phase 4: Relationship, Finance, Ecosystem, Mobile
- Tabs: People, Finance, Marketplace, Infinite.
- Exit criteria:
  - tri-pane data workflows complete
  - approvals and routing integrated with Notifications/Timeline

## Acceptance Criteria
1. All 23 tabs render unique interiors tied to their declared pattern.
2. No tab uses hardcoded seeded content in production route.
3. Mission Control supports task/cron inspect, add, edit, run, enable/disable.
4. Chat `+` menu and mode chips work for all listed actions; Games submenu launches Cloud Jump panel.
5. Long feeds/lists are paged or virtualized and remain performant.
6. Critical actions are fully auditable in Timeline.

## Implementation Guardrails
- Do not alter global shell structure in this plan’s implementation branch.
- Keep changes scoped to tab interior templates/components/data wiring only.
- Maintain existing theme tokens and visual language while differentiating layouts.
