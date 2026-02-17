# Thomas Vault Fortress (Paranoid Build)

A local-first vault broker designed for **prompt-injection resistance** and safe secret handling in an agent system like Thomas.

## Core properties
- Manual unlock (“vault door”) with TTL + inactivity timeout
- Scope-based access (profile/api/logins/etc.)
- LLM sees **handles** like `vault://api/openai`, not plaintext
- Tools authenticate with per-tool HMAC keys
- Replay resistance with one-time nonces
- High/critical secrets require **single-use confirm tokens** minted by UI
- Append-only, hash-chained audit log + verification

## IPC boundary
Secrets are released only over IPC:
- Windows: named pipe `\\.\pipe\thomas-vault-broker`
- macOS/Linux: unix socket in OS temp dir

HTTP is used only for the UI; there is **no HTTP endpoint that returns secrets**.

## Quickstart
```bash
npm install
npm run build
npm test

# init (one-time) via UI or CLI:
node dist/cli/index.js init --db ./.vault/vault.db --password "strong passphrase"

# start broker
npm run broker -- --db ./.vault/vault.db

# start UI
npm run ui -- --port 4318
```

Open: http://127.0.0.1:4318/vault

## Windows service (separate context)
See `scripts/windows/INSTALL_SERVICE.md`.

## Docker tool sandbox (optional)
See `scripts/sandbox/DOCKER_SANDBOX.md`.
