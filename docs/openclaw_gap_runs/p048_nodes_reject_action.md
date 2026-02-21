# P048 — Nodes reject action

## What this adds

Thomas gains a native **nodes reject-action** capability: a pending action for a node can be marked
as **rejected**, optionally recording a human-readable reason.

This supports both operators and automation.

## Contracts

**Input**
- `node_id` (string, required)
- `action_id` (string, required)
- `reason` (string, optional)

**Output**
- `status="rejected"`
- `updated_at` (UTC ISO-8601)

## Deterministic errors

- `invalid_input` — malformed payload (missing/invalid ids, reason too long, etc.)
- `missing_config` — no state/config available to locate the action store file
- `not_found` — action does not exist for the node
- `external_failure` — storage I/O or corrupt state file

## Automation support

- CLI supports `--json` for machine-readable output.
- Server integration exposes an aiohttp handler plus input/output JSON schemas.

## Storage model (CLI/offline)

The default backend is a small JSON store:

- state directory resolved from `THOMAS_STATE_DIR`, then `THOMAS_HOME/state`, else `~/.thomas`
- file name: `node_actions.json` (overrideable via `THOMAS_NODE_ACTIONS_PATH`)
