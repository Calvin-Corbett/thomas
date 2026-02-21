# Module Audit Workflow

Thomas now keeps a signed module-level audit ledger in:

- `docs/ops/module_audit_log.json`

This is separate from file-write audits. It answers:

- Which major module was last audited
- Who performed the audit (for example `doctor-bot`)
- When it happened
- What status was recorded (`pass`, `warn`, `fail`)
- A tamper-evident signature chain per module

## Record an audit

```bash
python scripts/record_module_audit.py \
  --module server \
  --auditor doctor-bot \
  --status pass \
  --summary "Replay endpoints reviewed after auth patch"
```

Optional signing key for HMAC signatures:

- Env var: `THOMAS_AUDIT_SIGNING_KEY`
- Or CLI: `--signing-key ...`

Without a key, SHA-256 signatures are still written (integrity-only, not secret-backed).

## Gate enforcement

CI enforces `scripts/check_module_audit_gate.py` for major-module changes.

When files under `thomas/<major_module>/` change, the gate requires:

- `docs/ops/module_audit_log.json` updated
- `CHANGELOG.md` updated
- Fresh, signed audit entries for touched modules

Default freshness window is 30 days (`--max-age-days`).

