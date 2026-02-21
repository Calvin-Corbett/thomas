# P028 – Node host state store

This gap run adds a **host state store** to Thomas: a small, local, file-backed persistence layer that can keep *per-host* state snapshots between runs.

The intent is to support node and browser orchestration workflows that benefit from remembering lightweight facts about a host, such as:

- last-seen timestamp
- connectivity / reachability flags
- inventory (OS, browser version, driver versions)
- any other JSON-serializable metadata used by automation

## Design

- **Storage model:** one JSON file per host ID in a configured directory
- **Schema:** `thomas.node_host_state.v1`
- **Deterministic errors:** stable error `code` + message + details (JSON-friendly)
- **Atomic writes:** temp file + rename; best-effort fsync
- **Automation output:** `--json` emits machine-readable JSON payloads

## Configuration

Store directory resolution order:

1. Explicit CLI `--store-dir`
2. Environment variables:
   - `THOMAS_NODE_HOST_STATE_DIR`
   - `THOMAS_STATE_DIR`
   - `THOMAS_DATA_DIR`
3. Default: `$XDG_STATE_HOME/thomas/node_host_state` or `~/.local/state/thomas/node_host_state`

## CLI

The command is exposed under the Nodes command group as:

- `host-state-store set <host_id> --state <json>`
- `host-state-store set <host_id> --merge --state <json>`
- `host-state-store get <host_id>`
- `host-state-store list`
- `host-state-store delete <host_id>`

All commands accept:

- `--store-dir <path>`: override store directory resolution
- `--json`: machine-readable output mode

`set` also supports:

- `--state '-'` or `--state-file '-'` to read JSON from stdin
- `--updated-at <iso8601>` to override timestamp (must include timezone)
- `--merge` to shallow-merge the provided state into an existing record

## Example

```bash
thomas nodes host-state-store --store-dir ./.thomas-state --json set hostA --state '{"os":"linux","reachable":true}'
thomas nodes host-state-store --store-dir ./.thomas-state --json get hostA
thomas nodes host-state-store --store-dir ./.thomas-state --json set hostA --merge --state '{"reachable":false}'
```

## Notes

This implementation is intentionally simple and dependency-free. If Thomas later needs a multi-process safe store with richer querying, it can be swapped behind the same contracts.
