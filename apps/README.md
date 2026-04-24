# Product Surface Scaffolds

This directory holds all client-facing delivery surfaces and shared contracts:

- `android/`: Android phone app client scaffold.
- `ios/`: iOS phone app client scaffold.
- `macos/`: macOS desktop client scaffold.
- `shared/`: Cross-platform shared contracts used by companion clients.
  - `shared/life_tracker/`: local SQLite life tracker CLI used by client-side flow tooling.

Quick routing:
- Phone apps: `android/`, `ios/`
- Desktop client: `macos/`
- Shared SDK/contracts: `shared/`

The private website/deployment surface is intentionally not part of the public
runtime repository.
