# Companion TypeScript SDK

Path: `thomas/companion/sdk/typescript`

This SDK is a typed client for Thomas companion endpoints (`/api/companion/v1/*`).

## Files

- `types.ts`: endpoint request/response typings
- `client.ts`: `CompanionClient` fetch wrapper
- `index.ts`: barrel exports

## Quick Usage

```ts
import { CompanionClient } from "./thomas/companion/sdk/typescript";

const client = new CompanionClient({
  baseUrl: "http://127.0.0.1:8899",
  apiToken: "<server-api-token-if-remote>",
  peerIdentity: "iphone-owner.ts.net",
});

const boot = await client.bootstrap({
  deviceId: "ios-1",
  includeSlotPayloads: true,
});

const check = await client.checkDeviceUpdates("ios-1", {
  channel: "stable",
});

const compliance = await client.complianceCheck({
  bundle_dir: "C:/bundles/companion.home-0.2.0",
  platform: "ios",
  distribution_channel: "app_store",
  commerce_model: "physical_or_off_app",
});

const ship = await client.ship({
  bundle_dir: "C:/bundles/companion.home-0.2.0",
  channel: "stable",
  execute: true,
});
```

## Build Type Check

```bash
npx tsc -p thomas/companion/sdk/typescript/tsconfig.json --noEmit
```

## Control-plane routes

Mutating routes require `X-Companion-Peer`.
Set it once via `peerIdentity` in `CompanionClient` options, or per call:

```ts
await client.applyBundle(
  { bundle_dir: "C:/bundles/companion.home-0.1.0" },
  { peerIdentity: "operator-laptop.ts.net" }
);
```

Release download:

```ts
const blob = await client.downloadReleaseBundle("stable.companion.home.0.2.0.20260220");
```
