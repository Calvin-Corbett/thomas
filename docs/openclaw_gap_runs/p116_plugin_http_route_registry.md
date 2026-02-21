# P116 - Plugin HTTP route registry

This run documents the Thomas-native **plugin HTTP route registry** behavior.

## What it does

Plugins can contribute HTTP routes (path-based handlers) that a Thomas Gateway
(or any embedded HTTP server) can mount. Thomas keeps a deterministic in-process
registry of these routes so they can be inspected by humans and automation.

Key properties:
- **Path normalization**: `webhook` becomes `/webhook`.
- **Uniqueness**: paths are globally unique; duplicates are rejected.
- **Stable output**: routes are sorted for reproducible results.

## CLI

List routes in human-readable form:

```bash
thomas plugins http-route-registry
```

Machine-readable JSON:

```bash
thomas plugins http-route-registry --json
```

JSON Schema for the `--json` output shape:

```bash
thomas plugins http-route-registry --schema
```

Optional: preload routes from a JSON config file (for offline inspection):

```bash
thomas plugins http-route-registry --config ./thomas.json --json
```

Note: some CLI loaders may also expose a short alias `http-routes`.
