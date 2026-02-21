# P050 — Nodes token rotate and revoke

This gap-run adds **Thomas-native** support for managing per-node access tokens.

- **Rotate**: revoke any currently-active token for a node and issue a new token.
- **Revoke**: revoke the currently-active token for a node (**idempotent**; repeated calls become a no-op).  
  If the token store (or node entry) doesn’t exist yet, revoke returns `no_active_token` rather than failing.

Tokens are stored **hashed + salted** in a small JSON store. The plaintext token only exists at rotation time (so operators can copy it onto the node).

## Storage

By default, the token store is:

- `~/.thomas/nodes_tokens.json`

You can override the store location with:

- `$THOMAS_NODES_TOKENS_PATH`
- or the CLI flag `--state PATH`

## CLI

This command group is designed to be mounted under:

- `thomas nodes token ...`

Commands:

- `thomas nodes token rotate <node-id> [--state PATH] [--json]`
- `thomas nodes token revoke <node-id> [--state PATH] [--json]`

### Examples

Rotate and print JSON:

```bash
thomas nodes token rotate nodeA --json
```

Revoke (human output):

```bash
thomas nodes token revoke nodeA
```

## Machine-readable contract

### Request

```json
{ "action": "rotate|revoke", "node_id": "string" }
```

### Response

Success:

```json
{
  "ok": true,
  "action": "rotate|revoke",
  "node_id": "string",
  "status": "rotated|revoked|no_active_token",
  "token": "string (rotate only)",
  "token_fingerprint": "string (rotate only)"
}
```

Failure:

```json
{
  "ok": false,
  "error": { "code": "string", "message": "string", "details": {} }
}
```
