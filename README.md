# Thomas

Thomas is a local-first AI workspace for chat, tools, memory, and automation.

Fresh install on Windows:

1. Run `run-ui.cmd`.
2. Open `http://127.0.0.1:8899` if it does not open automatically.
3. Complete Easy Setup.

If setup breaks, run `repair.cmd`. For manual setup, run `setup.cmd`. For startup diagnostics, run `bootdoctor.cmd`.

## What Ships in This Repo

- `thomas/` - core runtime, memory, tools, server, and web UI
- `apps/` - companion clients and supporting app surfaces
- `installer/` - Windows installer assets
- `scripts/` - automation, quality, packaging, and maintenance helpers
- `tests/` - regression and release checks

## Documentation

- `DOCUMENTATION_INDEX.md` - stable docs hub for the public release
- `docs/CHAT_EXECUTION_MODEL.md` - chat and execution flow
- `docs/WINDOWS_INSTALLER_GUIDE.md` - Windows installer build and packaging
- `docs/ops/DOCKER_DEPLOY.md` - container deployment
- `docs/ops/GATEWAY_SECURITY_RUNBOOK.md` - gateway hardening and incident response
- `docs/ops/RETRY_POLICY.md` - retry behavior and failure handling
- `SECURITY.md` - disclosure policy and supported security posture
- `KNOWN_ISSUES.md` - current rough edges and active limitations

## Development Notes

This is an early public product release. The repo includes contributor and automation infrastructure used to build Thomas, but normal use does not require understanding those internal workflows.

If you are changing code, start with `DOCUMENTATION_INDEX.md` and then move into the README for the specific area you are touching.

## Production Checklist

Before exposing a deployment externally:

1. Copy `.env.thomas.production.example` to `.env.thomas.production`, or provide equivalent environment variables.
2. Set a strong `THOMAS_SERVER_API_TOKEN`.
3. Set `THOMAS_MUTATING_CSRF_TOKEN` if you want request-level protection for mutating `/api` and `/gateway` routes.
4. Start with `THOMAS_ENV=production`.
5. Verify `/api/health` before opening external traffic.
6. Configure log rotation with `THOMAS_LOG_FILE`, `THOMAS_LOG_MAX_BYTES`, and `THOMAS_LOG_BACKUP_COUNT`.
7. Keep `THOMAS_ALLOW_REMOTE_PRODUCTION=1` disabled unless the deployment is explicitly intended for remote access.
