# Thomas Catch-Up Prompt Pack (2026-02-20)

Use this to run parallel ChatGPT tabs safely.

Historical note:
- This file is the starter wave (24 prompts).
- Full master pack: `docs/OPENCLAW_CATCHUP_PROMPT_PACK_216_2026-02-20.md`.
- Batch index CSV: `docs/OPENCLAW_CATCHUP_PROMPT_BATCH_INDEX_216_2026-02-20.csv`.

## Is This A Good Idea?

Yes, if run with controls.

It is a bad idea if prompts overlap files randomly.
It is a good idea if every prompt has:
- isolated file ownership
- explicit acceptance tests
- mandatory docs/changelog update
- no OpenClaw naming copy

Recommended concurrency:
- 6 to 10 tabs in parallel
- merge in 2 to 3 prompt batches, not all at once

## Global Rules For Every Prompt

Paste this block at the top of each prompt:

```text
You are implementing capabilities for Thomas in <repo_root>.

Hard constraints:
1) Do not copy OpenClaw naming, branding, internal identifiers, or docs text.
2) Implement Thomas-native names and architecture.
3) Own only the files listed in this prompt; do not edit outside them.
4) Add/expand tests for all new behavior.
5) Update docs/OPENCLAW_GAP_CHANGELOG.md with progress and remaining delta.
6) Keep code changes minimal, coherent, and production-safe.

Output requirements:
- Unified diff only.
- Then list exact test commands to run.
- Then list any follow-up risks.
```

## Prompt 01 - Browser Action Primitives

```text
Ownership:
- thomas/tools/browser.py
- thomas/cli/commands/browser_actions.py (new)
- thomas/cli/main.py
- tests/test_browser_actions_cli.py (new)

Goal:
Create Thomas-native browser action subcommands for high-frequency operations:
open-url, click, type-text, press-key, capture-shot, wait-for.

Requirements:
- Add robust argument validation and JSON output mode.
- Keep legacy `thomas browser smoke/status` working.
- Return structured error codes for automation scripts.
```

## Prompt 02 - Browser Profiles + Lifecycle

```text
Ownership:
- thomas/tools/browser.py
- thomas/cli/commands/browser_profiles.py (new)
- thomas/cli/main.py
- tests/test_browser_profiles_cli.py (new)

Goal:
Add Thomas browser profile lifecycle commands:
profile-create, profile-delete, profile-list, browser-start, browser-stop.

Requirements:
- Persist profile metadata in runtime state.
- Add safety checks for profile name collisions.
```

## Prompt 03 - Browser Diagnostics

```text
Ownership:
- thomas/tools/browser.py
- thomas/cli/commands/browser_diag.py (new)
- tests/test_browser_diag_cli.py (new)

Goal:
Add diagnostics commands:
console-log, net-requests, net-errors, dom-snapshot.

Requirements:
- JSON-first output with pagination/limit support.
- Add CLI tests for happy path and invalid parameter path.
```

## Prompt 04 - Browser End-To-End Reliability Tests

```text
Ownership:
- tests/test_browser_e2e_smoke.py (new)
- tests/test_browser_action_failures.py (new)
- scripts/run_browser_regression.ps1 (new)

Goal:
Create browser regression harness that validates action primitives + failure handling.

Requirements:
- Deterministic test fixtures.
- Quick mode and full mode.
```

## Prompt 05 - Node Host Lifecycle

```text
Ownership:
- thomas/server/node_host.py (new)
- thomas/cli/commands/node_host.py (new)
- thomas/cli/main.py
- tests/test_node_host_cli.py (new)

Goal:
Implement Thomas-native node host lifecycle commands:
host-install, host-run, host-status, host-restart, host-stop, host-remove.

Requirements:
- Local-only safe defaults.
- State persistence for lifecycle status.
```

## Prompt 06 - Node Operation Commands

```text
Ownership:
- thomas/cli/commands/nodes_ops.py (new)
- thomas/server/routes/nodes.py (new)
- tests/test_nodes_ops_cli.py (new)
- tests/test_nodes_api.py (new)

Goal:
Implement node operation commands:
nodes-list, nodes-invoke, nodes-notify, nodes-screen, nodes-camera, nodes-location.

Requirements:
- Define explicit request/response schema.
- Add auth checks on API route handlers.
```

## Prompt 07 - Gateway Control Depth

```text
Ownership:
- thomas/cli/commands/gateway.py
- thomas/server/routes/gateway_ops.py (new)
- tests/test_gateway_ops_cli.py (new)
- tests/test_gateway_ops_api.py (new)

Goal:
Expand gateway controls with:
start, restart, install, uninstall, probe, usage-cost.

Requirements:
- Preserve existing run/status/logs behavior.
- Add contract tests for command output structure.
```

## Prompt 08 - Approvals + System Commands

```text
Ownership:
- thomas/cli/commands/approvals.py (new)
- thomas/cli/commands/system.py (new)
- thomas/server/routes/system.py (new)
- tests/test_approvals_cli.py (new)
- tests/test_system_cli.py (new)

Goal:
Create first-class approvals/system surfaces:
approvals-get/set/allowlist and system-event/heartbeat/presence.
```

## Prompt 09 - Message Moderation Operations

```text
Ownership:
- thomas/cli/parity_compat.py
- thomas/cli/commands/messages_admin.py (new)
- tests/test_messages_admin_cli.py (new)

Goal:
Add Thomas-native message admin operations:
remove, edit, react, role-control, timeout-user, member-remove.

Requirements:
- Keep existing send/list/retry paths intact.
- Add clear safety checks and role guards.
```

## Prompt 10 - Message Search + Threads + Pins

```text
Ownership:
- thomas/cli/commands/messages_query.py (new)
- thomas/server/routes/messages.py (new)
- tests/test_messages_query_cli.py (new)

Goal:
Add message search, thread ops, and pin/unpin workflows with JSON output mode.
```

## Prompt 11 - Channel Lifecycle Workflows

```text
Ownership:
- thomas/cli/commands/channels.py
- thomas/integrations/channel_registry.py (new)
- tests/test_channels_lifecycle_cli.py (new)

Goal:
Add lifecycle flows:
channel-add, channel-remove, channel-login, channel-logout, channel-resolve, channel-capabilities.

Requirements:
- Keep provider logic modular and extensible.
- Preserve existing configure/status/test behavior.
```

## Prompt 12 - Directory + Pairing Depth

```text
Ownership:
- thomas/cli/commands/directory.py (new)
- thomas/cli/commands/pairing.py (new)
- tests/test_directory_cli.py (new)
- tests/test_pairing_cli.py (new)

Goal:
Implement directory and pairing flows:
self, peers, groups, pairing-list, pairing-approve, pairing-revoke.
```

## Prompt 13 - Plugin Runtime Foundation

```text
Ownership:
- thomas/plugins/registry.py (new)
- thomas/plugins/types.py (new)
- thomas/plugins/runtime.py (new)
- tests/test_plugins_registry.py (new)

Goal:
Create a Thomas plugin runtime foundation with:
plugin registry, loader contracts, hook registration, state model.

Requirements:
- No OpenClaw naming reuse.
- Keep runtime minimal but production-safe.
```

## Prompt 14 - Plugin Hook Pipeline

```text
Ownership:
- thomas/plugins/hooks.py (new)
- thomas/agent/loop.py
- tests/test_plugin_hooks_agent_loop.py (new)

Goal:
Integrate plugin hook points into agent lifecycle:
before-model, before-tool, after-tool, after-response.
```

## Prompt 15 - Plugin CLI Lifecycle

```text
Ownership:
- thomas/cli/commands/plugins.py (new)
- thomas/cli/main.py
- tests/test_plugins_cli.py (new)

Goal:
Move plugin CLI from parity placeholder behavior to runtime-backed lifecycle:
install, uninstall, list, info, enable, disable, update, doctor.
```

## Prompt 16 - Sample Plugin + Integration Tests

```text
Ownership:
- extensions/sample-inspector/ (new)
- tests/test_sample_plugin_integration.py (new)
- docs/plugins/PLUGIN_AUTHORING.md (new)

Goal:
Ship one reference plugin and integration tests proving registry + hooks + CLI flow.
```

## Prompt 17 - Memory Command Family

```text
Ownership:
- thomas/cli/commands/memory.py (new)
- thomas/server/routes/memory_ops.py (new)
- tests/test_memory_cli_ops.py (new)

Goal:
Add memory commands:
memory-index, memory-search, memory-status, memory-help.

Requirements:
- Wire to existing memory fabric where possible.
- No duplicate storage systems.
```

## Prompt 18 - Security Command Family

```text
Ownership:
- thomas/cli/commands/security.py (new)
- thomas/server/routes/security.py (new)
- tests/test_security_cli.py (new)

Goal:
Implement security audit CLI:
security-audit, security-config-check, security-help.

Requirements:
- Include clear red/yellow/green result structure.
```

## Prompt 19 - Continuous Gap Score Script

```text
Ownership:
- scripts/score_openclaw_gap.py (new)
- docs/OPENCLAW_GAP_CHANGELOG.md
- tests/test_gap_score_script.py (new)

Goal:
Create a script that computes current Thomas-vs-benchmark gap score from:
LOC, test LOC, command-depth deltas, extension count.

Requirements:
- Output JSON + markdown table.
- Deterministic and CI-safe.
```

## Prompt 20 - CI Guard For Gap Tracking

```text
Ownership:
- .github/workflows/robustness-gates.yml
- scripts/check_openclaw_gap_gate.py (new)
- tests/test_openclaw_gap_gate.py (new)

Goal:
Add CI gate that fails if:
- gap score regresses
- docs/OPENCLAW_GAP_CHANGELOG.md was not updated on capability PRs.
```

## Prompt 21 - Channel Integration Expansion Skeleton

```text
Ownership:
- thomas/integrations/discord.py (new)
- thomas/integrations/slack.py (new)
- thomas/integrations/__init__.py
- tests/test_integrations_discord_slack.py (new)

Goal:
Build first-class Discord/Slack integration modules (not only health probe logic).
```

## Prompt 22 - Gateway API Compatibility Endpoints

```text
Ownership:
- thomas/server/routes/openai_compat.py (new)
- thomas/server/routes/responses_compat.py (new)
- tests/test_openai_compat_routes.py (new)

Goal:
Add compatibility endpoints for external clients while preserving Thomas-native internals.

Requirements:
- Include auth enforcement and rate-limit checks.
```

## Prompt 23 - Command-Depth Documentation Generator

```text
Ownership:
- scripts/generate_cli_depth_report.py (new)
- docs/cli/COMMAND_DEPTH_REPORT.md (new)
- tests/test_cli_depth_report.py (new)

Goal:
Generate a report that lists every Thomas command and subcommand count, with trend snapshots.
```

## Prompt 24 - Release Readiness Checklist For Catch-Up

```text
Ownership:
- docs/OPENCLAW_CATCHUP_RELEASE_CHECKLIST.md (new)
- docs/OPENCLAW_GAP_CHANGELOG.md

Goal:
Create a release checklist covering:
capability completion, regression tests, docs, migration notes, rollback plan.
```

## Merge Cadence

After each prompt result:
1. Apply patch in local branch.
2. Run prompt-specific tests.
3. Run `pytest -q` for impacted suites.
4. Update `docs/OPENCLAW_GAP_CHANGELOG.md`.
5. Merge only if tests pass.

Do not merge multiple untested prompt outputs together.


