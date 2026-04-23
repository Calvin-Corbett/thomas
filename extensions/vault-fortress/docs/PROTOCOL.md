# Protocol (IPC)

Frames are length-prefixed JSON messages.

Envelope:
- `id`: correlation id
- `role`: `ui` or `tool`
- `op`: operation
- `ts`: ISO timestamp
- `bodyB64u`: base64url-encoded JSON body
- `auth` (tool only): `{ toolId, nonce, sig }`

Tool signature:
`sig = HMAC_SHA256(toolKey,  ts + "." + bodyB64u + "." + nonce + "." + op )` (base64url)

Replay protection:
- broker stores `(toolId, nonce)` in `used_nonces` and rejects duplicates.

Confirm tokens:
- minted by UI via broker (server-key HMAC)
- bound to `{ref, purpose, expiresAt, tokenId}`
- single-use; tokenId stored in `used_confirm_tokens`

Operations:
UI:
- `status`, `init`, `unlock`, `lock`, `list`, `put`, `toolAdd`, `mintConfirm`

Tool:
- `resolve` -> `{ ref, purpose, confirmToken? }`
