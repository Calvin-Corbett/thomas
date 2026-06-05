# Module: plugins

| Field            | Value                                                     |
|------------------|-----------------------------------------------------------|
| Status           | functional (install/CLI management only — runtime hook interception not wired)|
| Last assessed    | 2026-03-18                                                |
| Assessed by      | claude-opus-4-6 (Cowork session) + the product owner |
| Used in prod     | yes — desktop plugin install/enable/disable/uninstall works|
| Has real tests   | partial (test_suite_contract.py exists)                   |
| Blocking issues  | 3 files are placeholder, 2 files have competitor refs     |

## What This Is

The plugin/extension system for Thomas. 16,000 lines across 37 files.
This module handles plugin packaging, manifest validation, discovery, install,
enable/disable, hooks (before/after model, before/after tool, after response),
tool injection, config validation, diagnostics, and CLI commands.

**NOTE:** The actual marketplace UI and install routes live in `thomas/server/`
(`marketplace_catalog_aiohttp.py`, `plugin_hosting.py`, `desktop_plugins*.py`).
This module is the underlying plugin runtime. The server module is the storefront.

## Product Vision (from the product owner, 2026-03-18)

The marketplace is WAY bigger than just plugins. The full vision:

- **The marketplace is how you add anything to Thomas.** Plugins, channels,
  tools, memory modules, integrations — anything modular. It's the app store
  for your assistant.
- **Well-organized with filtering.** Browse by category (channels, tools,
  memory, etc.), search, filter. Not a flat list.
- **You don't have to go to the marketplace.** Tell Thomas "add Discord support"
  and Thomas finds it and installs it. Conversational install.
- **Auto-syncs from the website.** the product owner pushes marketplace content to the
  Thomas website, and Thomas pulls the latest catalog automatically. Always
  fresh.
- **Mix of official and third-party.** Official Thomas-made modules (quality
  guaranteed) alongside user-imported/third-party content. Clear distinction
  between the two.
- **Thomas can code what's missing.** If something isn't in the marketplace,
  Thomas can read any other agentic tool's docs, understand what it does,
  and build an integration himself. He's a developer too.
- **Master importer.** Thomas should be able to go to any competing product,
  read its architecture, copy what it needs, and import the functionality.
  He can even run other tools as sub-agents.

## What Actually Works (verified)

- **Plugin packaging** (`p097_plugin_package_bootstrap.py`): Bundle creation. Works.
- **Manifest validation** (`p098_plugin_manifest_schema.py`): Schema checking. Works.
- **Install/uninstall** (`p102`, `p103`): Local install from path, cleanup. Works.
- **Enable/disable** (`p101`): State store for toggling plugins. Works.
- **Hook system** (`p107-p112`): Before/after model, before/after tool, after
  response hook *modules* exist and are unit-tested in isolation
  (`tests/prompt_pack/test_p108..p112*`), and are registered via the CLI parity
  commands. **NOT yet invoked during an actual agent turn** — see Known Gaps.
  The agent loop (`thomas/agent/loop_*.py`) does not call `p108.run_hook`, so
  installed/enabled plugins' `before_model`/`before_tool`/`after_tool`/
  `after_response` callbacks never fire on a live request.
- **Extension catalog** (`extension_catalog_runtime.py`): Loads and validates
  extension pack catalogs from disk. Works.
- **Desktop plugin facade** (in `thomas/server/`): Install, enable, uninstall
  from the web UI. Added in 0.14.35. Works.
- **Life Manager plugin** (`extensions/life-manager/`): First real installable
  plugin with tasks/agenda/habits/goals. Works.

## What Is Placeholder / Not Working

**WARNING: These files EXIST but do NOT function:**

- `github_marketplace.py` — **PLACEHOLDER.** Source placeholder only.
  Was supposed to connect to GitHub marketplace. Not implemented.
- `platform_scanner.py` — **PLACEHOLDER.** Source placeholder only.
  Was supposed to scan for available platforms/integrations. Not implemented.
- `external_skill_adapter.py` — **PLACEHOLDER.** Source placeholder only.
  Was supposed to adapt external skills into Thomas format. Not implemented.

## What Has NOT Been Verified

The numbered `p*` files (p097-p123) follow a pattern that suggests batch
generation. Many have real code. The following have NOT been individually
confirmed as functional:

- `p100_plugin_discovery_scanner.py` (875 lines) — may or may not scan real sources
- `p104_plugin_update_planner.py` (859 lines) — update planning logic, unverified
- `p113_plugin_tool_provider_injection.py` — tool injection, unverified
- `p114_plugin_service_lifecycle_manager.py` — service lifecycle, unverified
- `p115_plugin_gateway_handler_registry.py` — gateway handler, unverified
- `p116_plugin_http_route_registry.py` — HTTP route registration, unverified
- `p118_plugin_diagnostics_collector.py` — diagnostics, unverified
- `p119_plugin_doctor_command.py` — doctor command, unverified
- `p123_sample_plugin_skeleton_extension.py` — sample/skeleton, likely scaffold

## Pre-Public Cleanup

- `competitor_evo_scope.py` — contains competitor references. Must scrub or delete.
- `competitor_intel_store.py` — contains competitor references. Must scrub or delete.
- Multiple `p*` files have 1 competitor reference each (see PRE_PUBLIC_CLEANUP.md)

## Known Gaps

- No "conversational install" — can't just tell Thomas to add something yet
- No auto-sync from website catalog (marketplace content is local only)
- No category filtering in marketplace UI
- 3 key files are source placeholders
- Competitor reference files need scrubbing
- **p107-p112 hook callbacks never fire during actual agent turns.** The hook
  modules and the `p108` runner (`run_hook`) are built and unit-tested, but
  nothing wires them into the live agent loop or the server chat path. The loop
  (`thomas/agent/loop_core.py` / `loop_execution.py` / `loop_tool_exec.py`) has
  no plugin-manager handle, `AgentLoop.__init__` takes no hook-runner argument,
  and no runtime registry of *enabled plugin instances* exists to pass to
  `run_hook` (only install state in `installed_plugins.json` and the
  `p105` registry data model). Wiring is intentionally deferred: it requires a
  new enabled-plugin loader/registry singleton plus a hook-runner injected into
  `AgentLoop` at construction time, which is a cross-layer change to the core
  loop and out of scope for a surgical wiring fix. See the wiring-audit deferral
  note for misc-singletons-02 for the full design.
- No STATUS.md existed before this one (added 2026-03-18)

## Do Not Touch

- `extension_catalog_runtime.py` — stable catalog loader, handles UTF-8 BOM edge case
- `desktop_plugins.py` (in server/) — facade only, edit the `_manifest` or `_runtime` files
