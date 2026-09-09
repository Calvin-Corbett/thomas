# Module Audit Workflow

Thomas now keeps a signed module-level audit ledger in:

- `docs/ops/module_audit_log.json`

This is separate from file-write audits. It answers:

- Which major module was last audited
- Who performed the audit (for example `doctor-bot`)
- When it happened
- What status was recorded (`pass`, `warn`, `fail`)
- A tamper-evident signature chain per module
- Which changed files were explicitly covered (`files_touched`)
- Content hashes for covered files (`file_hashes`) so edits invalidate stale sign-off
- Captured findings/issues for follow-up (`issues`)

## Record an audit

```bash
python scripts/record_module_audit.py \
  --module server \
  --file thomas/server/app.py \
  --file thomas/server/routes/chat_aiohttp.py \
  --auditor doctor-bot \
  --status pass \
  --summary "Replay endpoints reviewed after auth patch" \
  --issue "Route file still exceeds target size; follow-up split pending"
```

Optional signing key for HMAC signatures:

- Env var: `THOMAS_AUDIT_SIGNING_KEY`
- Or CLI: `--signing-key ...`

Without a key, SHA-256 signatures are still written (integrity-only, not secret-backed).

## Gate enforcement

CI enforces `scripts/forge/gates/module_audit_gate.py` for major-module changes.

When files under `thomas/<major_module>/` change, the gate requires:

- `docs/ops/module_audit_log.json` updated
- `CHANGELOG.md` updated
- Fresh, signed audit entries for touched modules
- Latest module audit must list every changed module file in `files_touched`
- Latest module audit must carry matching `file_hashes` for each changed file

Default freshness window is 30 days (`--max-age-days`).

## 24h Freshness Status

Use the status report to see repo-wide freshness and issue totals:

```bash
python scripts/module_audit_status.py --max-age-hours 24 --json
```

Use `--strict` to return non-zero when any module is stale/missing/invalid.

## Full Sweep

To refresh all major modules in one pass and capture architecture debt as issues:

```bash
python scripts/module_audit_sweep.py --auditor "$AGENT_ID" --json
```
