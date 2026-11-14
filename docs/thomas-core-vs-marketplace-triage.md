# Thomas Core vs Marketplace Triage

This document is the family-level source of truth for the `chatgpt` and `round 2` bundle batches.
Use it to decide what belongs in Thomas core runtime, what should ship as marketplace modules, and what should stay out of the shipped surface until it is real.

## Decision Matrix

| Family | Source Batch | Current Live Status | Decision | Why | Next Action |
| --- | --- | --- | --- | --- | --- |
| Browser command/runtime substrate (`p001`-`p026`) | `chatgpt` | Mostly real foundation | Core now | Browser execution, tabs, uploads, cookies, telemetry, and artifacts are substrate, not optional product add-ons. | Keep in runtime, wire through stable CLI/server surfaces, and test the base flows. |
| Node host/runtime substrate (`p027`-`p034`) | `chatgpt` | Real foundation | Core now | Thomas cannot be an operator assistant without a stable node host and local execution substrate. | Keep in core and enforce config/lifecycle contracts. |
| Nodes/device surfaces (`p035`-`p052`) | `chatgpt` | Mixed but foundational | Core now | Camera, screen, notify, invoke, approvals, pairing, and route primitives are part of the device/runtime substrate. | Keep in core, but trim dead entrypoints and verify the operator-facing paths. |
| Message schema and base CRUD/search/thread flows (`p053`-`p060`) | `chatgpt` | Base flows are live | Core now | Message persistence and retrieval are required for chat, memory, and UI continuity. | Keep the basic schema and CRUD/search/thread surface in core. |
| Message advanced commands (`p061`-`p074`) | `round 2` | Mixed; some real, some noop | Later after substrate | Useful, but not all are required for Thomas to function as an assistant. | Promote only the commands with real runtime paths and tests; demote noop commands. |
| Channel architecture and registry substrate | `round 2` | Partly wired | Core now | Core routing, registration, and compatibility surfaces are required to support channel modules. | Keep the substrate in core, then move channel-specific behaviors out. |
| Channel-specific ops and enrichers | `round 2` | Many exposed via proxy/noop | Marketplace module | These are add-on behaviors tied to integrations or workflows, not required substrate. | Convert into installable channel modules with manifests and tests. |
| Plugin runtime, manifests, install/enable/disable/uninstall | `round 2` | Real and production-used | Core now | This is the install system Thomas needs to support everything else. | Keep in core and harden the manifest/signature/update path. |
| Plugin diagnostics, discovery scanners, update planners | `round 2` | Unverified or partial | Later after substrate | Valuable operational tooling, but not critical to initial runtime correctness. | Verify each piece individually before promotion. |
| Gateway mounted compat subset (`p139`, `p140`, `p141`, `p144`, `p145`, `p146`) | `round 2` | Real mounted routes | Core now | The mounted compat routes are part of Thomas's public runtime/API surface. | Keep and expand only through tested route registration. |
| Gateway scaffold bundles (`p125`-`p150` outside mounted subset) | `round 2` | Mixed; many scaffold | Scaffold/proxy until proven real | Existing filenames are not proof of runtime value. | Audit each route and hide non-real surfaces from shipped capability views. |
| Domain inventory under `thomas/marketplace/**` | `round 2` and broader repo | Mostly real inventory, not live | Marketplace module | These families fit the "everything assistant" vision, but they do not belong in core runtime by default. | Wrap in manifests, tool surfaces, and tests before shipping as installables. |
| Extension packs under `extensions/**` | Broader repo | Real installable/module inventory | Marketplace module | This is already the natural packaging boundary for optional Thomas capabilities. | Make the website catalog the canonical host and desktop sync client for these packs. |
| Placeholder/plugin bridge/noop commands | `round 2` and broader repo | Not real user-facing runtime | Scaffold/proxy until proven real | Surfaced commands that only noop or placeholder are product debt, not capabilities. | Hide from primary UI and CLI help until they execute real logic. |
| Memory substrate | Broader repo | Important but incomplete | Core now | Memory is part of Thomas's identity and must be a core runtime concern. | Prioritize core memory wiring before widening optional module scope further. |

## Core Scope

The core runtime should stay small:

- Chat, memory substrate, approvals, tools, browser/node/nodes substrate
- Plugin runtime and install lifecycle
- Marketplace sync, catalog, install, update, uninstall surfaces
- Stable CLI/server plumbing

## Marketplace Scope

The marketplace is the broad surface:

- Domain packs and vertical tools
- Channel add-ons and provider-specific integrations
- Alerting, analytics, compliance, workflow, and specialist packs
- Anything useful that Thomas can install but does not need to boot as an assistant

## Product Rule

Thomas can be an everything assistant without turning core runtime into an everything monolith.
Broad capability belongs in the marketplace; predictable substrate belongs in core.
