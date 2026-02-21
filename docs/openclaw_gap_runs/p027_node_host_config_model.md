# P027 — Node host config model

This gap-run implements a **node host configuration model** for Thomas.

The goal is to expose a small, stable JSON Schema for the configuration surface used by a headless **node host** (the remote execution node that connects to the Thomas gateway). The model is intended to be consumed by both humans and automation, so it supports a machine-readable `--json` mode.

## What shipped

- A Thomas-native model builder that returns:
  - `schema`: JSON Schema for node-host configuration.
  - `example`: a minimal example snippet (optional).
  - `uiHints`: lightweight labels/help strings (optional).
  - `current`: the currently configured node-host settings loaded from a config file (optional).
- Deterministic error codes for:
  - invalid input / invalid config
  - missing config
  - external failures (filesystem I/O)
- A CLI command under the `nodes` command group:
  - `nodes host-config-model --json`

## Output envelopes

The CLI emits a stable success/error envelope:

- **Success:** `{ "ok": true, ...modelFields }`
- **Failure:** `{ "ok": false, "error": { "code": "...", "message": "...", "details": {...} } }`

This keeps `schema` at the top level while also providing a standard `ok` flag for automation.

## Notes

- The schema intentionally avoids complex JSON Schema features (e.g. `patternProperties`, deep `oneOf` trees) to maximize client compatibility.
- When `--include-current` is used, the command will accept either:
  - a full config file containing a top-level `nodeHost` / `node_host` section, or
  - a file containing only the node-host object itself.
