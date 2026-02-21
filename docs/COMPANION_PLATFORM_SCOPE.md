# Companion Platform Scope (Frozen Contract v0)

Last updated: 2026-02-20

This defines the non-negotiable baseline for the Thomas companion app so it
can be "infinitely customizable" without becoming unsafe or unstable.

## Product Direction

The companion must be built as:
- immutable host kernel
- signed module update pipeline
- module-driven screens and behavior
- tailscale-first control plane

The companion must **not** be built as:
- arbitrary self-mutating production core
- unsigned remote code execution
- direct kernel file overwrite by modules

## Minimum Requirements (Must Exist Before Broad Release)

1. Stable kernel/runtime boundary
   - Host kernel remains stable; modules are replaceable.
   - Kernel files are immutable by module updates.

2. Versioned module contract
   - Module manifest requires id/version/entrypoint/permissions/slots/ui schema.
   - Backward compatibility rules apply via semver.

3. Signed updates with rollback
   - Every production bundle must be signed and verified before apply.
   - Failed applies must preserve previous module files via backup rollback path.

4. Tailscale identity enforcement
   - Companion control plane must be tailscale-only for remote update/control.
   - Localhost dev mode is allowed explicitly for development.

5. Permission gating
   - Module declares permissions; host enforces allowlist.
   - No implicit elevated capabilities.

6. Auditability
   - Update verification/apply actions produce auditable records.
   - Module source bundle and timestamp are tracked in registry.

## Current Scaffold in Thomas

Core package:
- `thomas/companion/contracts.py`
- `thomas/companion/kernel.py`
- `thomas/companion/network.py`
- `thomas/companion/registry.py`
- `thomas/companion/update.py`
- `thomas/companion/runtime.py`
- `thomas/companion/devices.py`
- `thomas/companion/releases.py`
- `thomas/companion/audit.py`

CLI:
- `thomas companion init`
- `thomas companion status`
- `thomas companion module-list`
- `thomas companion verify-bundle --bundle <dir>`
- `thomas companion apply-bundle --bundle <dir> --execute`
- `thomas companion write-template --out-dir <dir>`

HTTP API scaffold (aiohttp):
- `GET /api/companion/v1/status`
- `GET /api/companion/v1/contract`
- `GET /api/companion/v1/studio/capabilities`
- `GET /api/companion/v1/bootstrap`
- `GET /api/companion/v1/modules`
- `GET /api/companion/v1/slots`
- `GET /api/companion/v1/slots/{slot}`
- `POST /api/companion/v1/modules/{module_id}/enable`
- `POST /api/companion/v1/modules/{module_id}/disable`
- `POST /api/companion/v1/studio/build-bundle`
- `POST /api/companion/v1/bundles/preview`
- `POST /api/companion/v1/bundles/verify`
- `POST /api/companion/v1/bundles/apply`
- `POST /api/companion/v1/ship`
- `GET /api/companion/v1/devices`
- `POST /api/companion/v1/devices/register`
- `POST /api/companion/v1/devices/{device_id}/heartbeat`
- `POST /api/companion/v1/devices/{device_id}/updates/check`
- `POST /api/companion/v1/devices/{device_id}/pin-release`
- `POST /api/companion/v1/devices/{device_id}/unpin-release`
- `GET /api/companion/v1/releases`
- `GET /api/companion/v1/releases/{release_id}`
- `GET /api/companion/v1/releases/{release_id}/manifest`
- `GET /api/companion/v1/releases/{release_id}/download`
- `POST /api/companion/v1/releases/publish`
- `POST /api/companion/v1/releases/{release_id}/rollout`
- `POST /api/companion/v1/releases/{release_id}/promote`
- `POST /api/companion/v1/releases/{release_id}/rollback`
- `GET /api/companion/v1/audit/events`

Companion Builder screen in Thomas web UI:
- `GET /companion`

Control-plane identity note:
- mutating routes (`enable/disable/studio/verify/apply/ship/register/heartbeat/check/pin/unpin/publish/rollout/promote/rollback`)
  enforce tailscale identity policy from `policy.json`
- localhost is allowed for development

Bundle API payloads:
- verify: `{ "bundle_dir": "..." }`
- apply: `{ "bundle_dir": "...", "dry_run": true }` or
  `{ "bundle_dir": "...", "execute": true }`

Companion-app handoff contract:
- `docs/COMPANION_APP_INTEGRATION.md`

## Handoff Guidance For Companion App Work

Your brother should build against this frozen v0 scope:
- assume the kernel contract is stable
- implement UI/modules against manifest contract
- treat signed bundle flow as required infrastructure, not optional polish

When changing this scope:
- update this doc
- update `README.md` companion section
- add/adjust tests for contract and update verification logic
