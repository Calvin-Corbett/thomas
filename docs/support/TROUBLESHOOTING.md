# Troubleshooting Playbook

This is the self-serve support surface for production Thomas operators.

## Fast triage sequence

1. Run `thomas doctor`.
2. Run `python scripts/config_validator.py --json`.
3. Run `GET /api/setup/bootstrap` to confirm machine readiness.
4. Run `GET /api/setup/diagnostics` for runtime config+policy diagnostics.
5. If setup failed, run `POST /api/setup/repair` with options used by the user.
5. Capture logs and route to the owning lane (onboarding, security, runtime, release).

6. For code-path bug hunts, use CLI run triage (no UI required) and copy `run_id` into handoff notes:
   - `thomas runs list --json --ok 0 --limit 50` — list recent failed runs.
   - `thomas runs show <run_id>` — inspect run metadata and summary stats.
   - `thomas runs events <run_id> --start 0 --limit 400 --json` — step-by-step event timeline.
   - `thomas runs replay <run_id> --from 0 --json` — stream replay output.
   - `thomas runs export <run_id> --json` — machine-readable debug artifact.
   - `GET /api/runs/<run_id>/export.json` remains available for internal tooling.

## Common failure modes

1. Setup loops or never completes
- Signal: onboarding reopens every launch.
- Check: preferences onboarding state (`setup_completed`, `current_step`).
- Action: clear stale onboarding step and rerun guided setup; verify telemetry events are emitted.

2. Local model path fails
- Signal: local profile selected but no responses.
- Check: Ollama installed and `/api/tags` reachable from `/api/setup/bootstrap`.
- Action: run repair flow with local dependencies enabled.

3. Cloud profile fails auth
- Signal: 401/403 from model handshake.
- Check: secret exists for active profile and base URL path is correct.
- Action: rotate key and revalidate profile handshake.

4. Session stalls under concurrent chat
- Signal: chat requests return conflict/lock response.
- Check: active run map and session lock telemetry.
- Action: allow active run to finish or cancel stale run before retry.

5. Workspace state appears reset
- Signal: missing rooms/layout after restart.
- Check: workspace file quarantine artifacts (`*.corrupt.*`) and backup recovery status.
- Action: restore from last-good backup and inspect corrupt payload.

6. Security header regression
- Signal: scanner flags missing CSP/COOP/CORP headers.
- Check: response headers on web routes.
- Action: restore default header middleware and rerun server access tests.

7. CI gate deadlock on required checks
- Signal: required check stays pending with no run.
- Check: workflow trigger paths, branch filters, and required-check names.
- Action: ensure required public workflows run on all PRs.

8. Config drift between environments
- Signal: works locally, fails in CI/prod.
- Check: validator output and environment overrides (`THOMAS_*`).
- Action: pin config explicitly and publish migration notes.

9. Webhook receive routes return `503` in remote mode
- Signal: `/webhooks/receive/github` or `/webhooks/receive/stripe` fails with signature-enforcement message.
- Check: `python scripts/config_validator.py --json` for `server.remote.webhook_signatures_disabled`, `webhooks.github.signature_secret_missing`, and `webhooks.stripe.signature_secret_missing`.
- Action: set `THOMAS_WEBHOOK_REQUIRE_SIGNATURES=1` and configure provider signing secrets (`THOMAS_GITHUB_WEBHOOK_SECRET`, `THOMAS_STRIPE_WEBHOOK_SECRET`).

## Escalation thresholds

1. Security issue with exploit path: immediate sev-1 incident process.
2. Onboarding completion drop >10% week-over-week: product emergency patch lane.
3. Soak failure that corrupts persisted state: release freeze until fixed.
4. Required-check workflow deadlock: release manager override only with written RCA.
