# Threat Model: Thomas Vault Fortress

This document is intentionally paranoid.

## Assets
- **Master Key (MK)**: decrypts all secrets. Must never leave broker memory.
- **Secrets**: API keys, logins, tokens, medical/legal docs, etc.
- **Tool keys**: per-tool HMAC keys, stored in DB.

## Adversaries
1) **Malicious prompt / injection** inside an LLM conversation
2) **Compromised tool process** (supply chain, malware, rogue plugin)
3) **Local attacker** on the same machine (another user account, malware)
4) **Network attacker** (should be irrelevant if no secret-over-HTTP)

## Trust boundaries
- UI (human-operated) ↔ Broker (IPC only)
- Tool processes ↔ Broker (IPC + HMAC)
- LLM ↔ Tools (LLM never sees plaintext secrets, only vault refs)

## Attack surfaces & mitigations
### Prompt injection (LLM tries to exfiltrate secrets)
**Mitigations**
- LLM sees `vault://...` references only.
- Tool requests require:
  - tool authentication (HMAC + nonce)
  - vault unlock session active
  - scope allowed for tool
  - scope currently unlocked
  - **confirm token** for high/critical secrets (single-use, purpose-bound)

### Replay attacks
**Mitigations**
- One-time nonces stored in DB (`used_nonces`).
- Confirm tokens also single-use (`used_confirm_tokens`).

### “LLM convinces tool to ask for everything”
**Mitigations**
- Tool is limited to configured scopes.
- Human unlocks scopes explicitly and temporarily.
- High/critical secrets require human confirmation token per access.

### Broker compromise
**Mitigations**
- Reduce blast radius by running broker as separate OS account/service.
- Store DB in locked-down directory.
- Optional container sandbox for tools.
- Audit log supports post-incident investigation.

## What this does NOT solve
- If your OS is fully compromised (keylogger + memory scraping), all bets are off.
- If a tool is malicious AND you give it a confirm token, it can use it.
  The system is designed so **humans must actively participate** to release sensitive secrets.
