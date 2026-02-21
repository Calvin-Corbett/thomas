# Companion App Integration Contract (v1)

Last updated: 2026-02-20

This is the integration contract your brother's app should target.

TypeScript SDK (ready to use):
- `thomas/companion/sdk/typescript/index.ts`
- `thomas/companion/sdk/typescript/types.ts`
- `thomas/companion/sdk/typescript/client.ts`

PC Builder UI (for preview + ship workflow):
- `GET /companion`

## Required Security Model

1. In remote mode, every request needs Thomas API auth (`Authorization: Bearer <token>` or `X-Api-Token`).
2. Control-plane routes also require tailscale identity:
   - send `X-Companion-Peer: <device-or-node>.ts.net`
   - localhost is allowed for dev only
3. Production updates are expected to be signed (`THOMAS_COMPANION_UPDATE_SECRET` set on host).

## Core App Boot Flow

1. `POST /api/companion/v1/devices/register` (once per install / sign-in).
2. `GET /api/companion/v1/bootstrap?device_id=<id>&include_slot_payloads=1`.
3. Render UI from `slot_payloads` (or call `GET /api/companion/v1/slots/{slot}` lazily).
4. Poll `POST /api/companion/v1/devices/{device_id}/updates/check`.
5. Send `POST /api/companion/v1/devices/{device_id}/heartbeat` periodically.

SDK bootstrap example:
```ts
import { CompanionClient } from "thomas/companion/sdk/typescript";

const client = new CompanionClient({
  baseUrl: "http://127.0.0.1:8899",
  apiToken: "<token-if-remote-mode>",
  peerIdentity: "iphone-owner.ts.net",
});

await client.registerDevice({
  device_id: "ios-1",
  platform: "ios",
  app_version: "1.0.0",
  channel: "stable",
});

const boot = await client.bootstrap({
  deviceId: "ios-1",
  includeSlotPayloads: true,
});
```

## Endpoint Surface

Read:
- `GET /api/companion/v1/status`
- `GET /api/companion/v1/contract`
- `GET /api/companion/v1/studio/capabilities`
- `GET /api/companion/v1/policy/profiles`
- `GET /api/companion/v1/policy/profile/{profile_id}`
- `GET /api/companion/v1/bootstrap`
- `GET /api/companion/v1/modules`
- `GET /api/companion/v1/slots`
- `GET /api/companion/v1/slots/{slot}`
- `GET /api/companion/v1/releases`
- `GET /api/companion/v1/releases/{release_id}`
- `GET /api/companion/v1/releases/{release_id}/manifest`
- `GET /api/companion/v1/releases/{release_id}/download`
- `GET /api/companion/v1/audit/events`

Mutating control-plane:
- `POST /api/companion/v1/modules/{module_id}/enable`
- `POST /api/companion/v1/modules/{module_id}/disable`
- `POST /api/companion/v1/studio/build-bundle`
- `POST /api/companion/v1/bundles/preview`
- `POST /api/companion/v1/bundles/verify`
- `POST /api/companion/v1/bundles/apply`
- `POST /api/companion/v1/compliance/check`
- `POST /api/companion/v1/ship`
- `POST /api/companion/v1/devices/register`
- `POST /api/companion/v1/devices/{device_id}/heartbeat`
- `POST /api/companion/v1/devices/{device_id}/updates/check`
- `POST /api/companion/v1/devices/{device_id}/pin-release`
- `POST /api/companion/v1/devices/{device_id}/unpin-release`
- `POST /api/companion/v1/releases/publish`
- `POST /api/companion/v1/releases/{release_id}/rollout`
- `POST /api/companion/v1/releases/{release_id}/promote`
- `POST /api/companion/v1/releases/{release_id}/rollback`

## Minimum Payload Shapes

Device register:
```json
{
  "device_id": "ios-1",
  "platform": "ios",
  "distribution_channel": "app_store",
  "storefront_region": "US",
  "app_build_id": "ios-build-1",
  "app_version": "1.0.0",
  "channel": "stable",
  "runtime_capability_set": ["push", "camera", "storage", "websocket"],
  "installed_modules": {
    "companion.home": "0.1.0"
  },
  "capabilities": ["push", "camera"],
  "metadata": {}
}
```

Heartbeat:
```json
{
  "platform": "ios",
  "distribution_channel": "app_store",
  "storefront_region": "US",
  "runtime_capability_set": ["push", "camera", "storage", "websocket"],
  "installed_modules": {
    "companion.home": "0.1.0"
  }
}
```

Update check:
```json
{
  "channel": "stable"
}
```

Update check response notes:
- `source` is `channel` or `pinned`.
- `pinned_release_id` is returned when the device is pinned (or explicitly requested).

Publish release (host-side operator action):
```json
{
  "bundle_dir": "C:/path/to/bundle",
  "channel": "stable",
  "actor": "owner",
  "platform": "ios",
  "distribution_channel": "app_store",
  "storefront_region": "US",
  "commerce_model": "physical_or_off_app",
  "url_allowlist": ["app.example.com"]
}
```

Ship in one step (verify + apply + publish):
```json
{
  "bundle_dir": "C:/path/to/bundle",
  "channel": "stable",
  "actor": "owner",
  "execute": true,
  "platform": "ios",
  "distribution_channel": "app_store",
  "storefront_region": "US",
  "policy_profile_id": "ios_app_store",
  "runtime_capability_set": ["push", "camera", "storage", "websocket"],
  "rollout_pct": 100,
  "target_devices": [],
  "exclude_devices": [],
  "min_app_version": "",
  "required_capabilities": [],
  "commerce_model": "digital_in_app",
  "store_billing_enabled": true,
  "ugc_enabled": false,
  "moderation_controls": [],
  "age_gate_enabled": false,
  "collects_personal_data": false,
  "privacy_policy_url": "",
  "url_allowlist": []
}
```

Pin a device to one release (override rollout/target filters for that pinned module update):
```json
{
  "release_id": "stable.companion.home.0.2.0.20260220T000000Z",
  "actor": "owner"
}
```

Adjust rollout/targeting for a release:
```json
{
  "rollout_pct": 25,
  "target_devices": ["ios-1", "android-2"],
  "exclude_devices": [],
  "min_app_version": "1.0.0",
  "required_capabilities": ["push"],
  "status": "active"
}
```

Run pre-ship compliance only (no apply/publish):
```json
{
  "bundle_dir": "C:/path/to/bundle",
  "platform": "ios",
  "distribution_channel": "app_store",
  "storefront_region": "US",
  "policy_profile_id": "ios_app_store",
  "commerce_model": "digital_in_app",
  "store_billing_enabled": true,
  "ugc_enabled": false,
  "url_allowlist": ["app.example.com"]
}
```

Build bundle from Studio payload (no manual zip step):
```json
{
  "module": {
    "id": "companion.custom",
    "version": "0.1.0",
    "entrypoint": "modules/companion.custom/ui/screen.json",
    "slots": ["home.main"],
    "permissions": ["ui.render", "storage.read"],
    "ui_schema_version": "0.1.0"
  },
  "screen_payload": {
    "screen_id": "home",
    "components": [{ "type": "text", "value": "hello" }]
  },
  "extra_files": [
    { "path": "modules/companion.custom/ui/theme.json", "content": { "accent": "#0ea5e9" } }
  ],
  "release_notes": "studio generated"
}
```

## What The App Should Treat As Source Of Truth

1. `bootstrap.slot_payloads` for current UI module payload.
2. `updates/check` response for available module releases.
3. `contract` response for required rules and endpoint inventory.
4. `studio/capabilities` response for permission allowlist, UI/data/action primitives, and templates.

## Non-goals For The Mobile App

1. Do not mutate kernel files directly.
2. Do not execute unsigned arbitrary code.
3. Do not bypass module manifest permissions or slot boundaries.
