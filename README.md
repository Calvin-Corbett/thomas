# Thomas

Thomas is a local-first AI workspace for chat, tools, memory, and automation.

## Quick Start on Windows

Fresh install: run `run-ui.cmd`.

1. Download the repo from GitHub with **Code -> Download ZIP**, or clone it with Git.
2. Extract the ZIP if you downloaded one.
3. Open the extracted `thomas` folder.
4. Double-click `run-ui.cmd`.
5. If Thomas asks to create `.venv` or install local runtime dependencies, approve it. These installs stay inside this repo folder.
6. Open `http://127.0.0.1:8899` if the browser does not open automatically.
7. Complete Easy Setup in the app.

If setup breaks, run `repair.cmd`. For a manual setup pass, run `setup.cmd`. For startup diagnostics, run `bootdoctor.cmd`.

## What to Expect

- First launch creates a local Python virtual environment in `.venv`.
- Thomas runs on your own machine by default.
- Model/provider setup happens in Easy Setup after the web UI opens.
- If Codex, Ollama, or API keys are not ready yet, Thomas should still start and show setup guidance.

## Everyday Use

Use Thomas first as a local chat workspace. Start the app with `run-ui.cmd`, open the browser UI, and use Easy Setup to connect the model path you want to use. You can add memory, tools, automation, and integrations after the basic chat path is working.

## Grow Into Advanced Thomas Safely

Thomas includes builder and automation surfaces, but you do not need them for first use. Keep the default local/protected posture until you understand what a tool or integration will do, and use `bootdoctor.cmd` or `repair.cmd` when setup state looks wrong.

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
