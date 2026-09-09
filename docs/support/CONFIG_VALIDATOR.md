# Config Validator Guide

Thomas ships a config validator for self-serve support and pre-release checks.

Command:

```bash
python scripts/config_validator.py --json
```

CLI equivalent:

```bash
thomas config validate --json
```

Optional config path:

```bash
python scripts/config_validator.py --config path/to/thomas.toml --json
```

## What it checks

1. Core schema validation from `thomas.core.config`.
2. Remote mode security posture warnings.
3. Remote webhook signature guardrails:
- blocks `THOMAS_WEBHOOK_REQUIRE_SIGNATURES=0` when `server.access_mode="remote"`.
- warns when GitHub/Stripe webhook signature secrets are missing while enforcement is active.
4. Dangerous shell setting warnings.
5. Missing API key checks for non-local providers.
6. Insecure non-local `http://` base URL warnings.

## Exit codes

1. `0`: no blocking errors.
2. `2`: one or more blocking errors.

Warnings do not fail the command but should be triaged before release.

## Typical usage in support

1. Ask user to run validator and share JSON output.
2. Match `code` values to support runbooks.
3. Apply fix and rerun until `ok=true`.

Common webhook-related `code` values:

1. `server.remote.webhook_signatures_disabled`
- Remote mode is running with signature enforcement explicitly disabled.
- Fix: unset `THOMAS_WEBHOOK_REQUIRE_SIGNATURES` or set it to `1`.
2. `webhooks.github.signature_secret_missing`
- Signature enforcement is active but GitHub signing secret is not configured.
- Fix: set `THOMAS_GITHUB_WEBHOOK_SECRET` (or `THOMAS_GITHUB_WEBHOOK_SECRETS`).
3. `webhooks.stripe.signature_secret_missing`
- Signature enforcement is active but Stripe signing secret is not configured.
- Fix: set `THOMAS_STRIPE_WEBHOOK_SECRET` (or `THOMAS_STRIPE_WEBHOOK_SECRETS`).

For server-side support, call `GET /api/setup/diagnostics` to retrieve the same
diagnostic shape plus runtime auth mode/profile summary.
